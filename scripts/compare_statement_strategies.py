"""Compare full-statement strategies using one frozen corpus and shared source checks."""
import argparse
import copy
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from reconciliation.token_usage import FIELDS, record
from scripts.benchmark_matching import number, save
from scripts.test_statement_matching import match_all, report, verify_strong


def signature(row):
    """Identify a bank allocation independently of model wording or decimal formatting."""
    value=[row['bank_id'],sorted((a['item_id'],format(number(a['amount']).normalize(),'f')) for a in row['allocations'])]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def shared_context(rows, base):
    """Apply the same non-monetary evidence follow-up to every strategy."""
    followups={r['bank_id']:r for p in (base/'contextual').glob('result-*.json')
               for r in json.loads(p.read_text(encoding='utf-8'))['decisions']}
    for row in rows:
        extra=followups.get(row['bank_id'])
        if extra and extra['assessment']!='none' and row['assessment']!='strong':
            row.update(assessment='tentative',reason=row['reason']+' Contextual follow-up: '+extra['reason'])
    return rows


def stage_timing(path):
    """Recover observed wall spans and attempt durations from durable event timestamps."""
    attempts = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            if event.get('id'):
                times = attempts.setdefault(event['id'], {})
                times['start' if event['status']=='started' else 'end'] = datetime.fromisoformat(event['at'])
    complete = [value for value in attempts.values() if 'start' in value and 'end' in value]
    durations = [(value['end']-value['start']).total_seconds() for value in complete]
    return {'method':'saved attempt timestamps; parallel wall span is not summed call durations',
            'wall_seconds':(max(v['end'] for v in complete)-min(v['start'] for v in complete)).total_seconds() if complete else 0,
            'attempt_seconds':durations, 'unknown_duration_attempts':len(attempts)-len(complete)}


def compare(base, workers):
    """Measure variants without repeating unchanged source-verification model calls."""
    all_facts=json.loads((base/'facts.json').read_text(encoding='utf-8'))
    facts={**all_facts,'items':[i for i in all_facts['items'] if i['id'].startswith('D')]}
    index=json.loads((base/'index.json').read_text(encoding='utf-8'))
    raw=json.loads((base/'raw-decisions.json').read_text(encoding='utf-8'))
    checked=json.loads((base/'source-checks.json').read_text(encoding='utf-8'))
    cache={signature(row):checked[row['bank_id']] for row in raw if row['bank_id'] in checked}
    cache_path = base/'source-verdict-cache.json'
    if cache_path.exists():
        cache.update(json.loads(cache_path.read_text(encoding='utf-8')))
    results={'20-lines':json.loads((base/'summary.json').read_text(encoding='utf-8'))}
    results['20-lines']['raw_strong']=sum(r['assessment']=='strong' for r in raw)
    for label,size,hybrid,local in [('40-lines',40,False,False),('hybrid-20-lines',20,True,False),('python-only',20,True,True)]:
        output=base/label
        completed = output/'strategy.json'
        if completed.exists():
            results[label] = json.loads(completed.read_text(encoding='utf-8'))
            continue
        save(output/'facts.json',facts)
        save(output/'index.json',index)
        start=time.perf_counter()
        raw_path=output/'raw-decisions.json'
        rows=json.loads(raw_path.read_text(encoding='utf-8')) if raw_path.exists() else match_all(facts,output,workers,size,hybrid,local)
        proposed=sum(r['assessment']=='strong' for r in rows)
        unresolved=[r for r in rows if r['assessment']=='strong' and signature(r) not in cache]
        reused=[r for r in rows if r['assessment']=='strong' and signature(r) in cache]
        for row in reused:
            record(output/'verification/token-usage.jsonl',{'status':'cached','stage':'matching_source_verification',
                   'model':'gpt-5.6-sol','source_verdict':signature(row),'usage':{k:0 for k in FIELDS}})
        if unresolved:
            newly_checked=verify_strong(unresolved,facts,index,output,workers)
            for before,after in zip(unresolved,newly_checked):
                cache[signature(before)]=after
        final=[copy.deepcopy(cache[signature(r)]) if r['assessment']=='strong' else copy.deepcopy(r) for r in rows]
        final=shared_context(final,base)
        report(final,all_facts,output)
        result=json.loads((output/'summary.json').read_text(encoding='utf-8'))
        result.update(raw_strong=proposed,source_verdicts_reused=len(reused),
                      new_source_checks=len(unresolved),wall_seconds=time.perf_counter()-start)
        save(output/'strategy.json',result)
        results[label]=result
        save(base/'strategy-comparison.json',results)
        save(base/'source-verdict-cache.json',cache)
        print(f"Finished {label}: {result['counts']}",flush=True)
    write_report(base, results)


def write_report(base, results):
    """Save comparable matching costs, incremental review costs and per-line outcomes."""
    for label, result in results.items():
        folder = base if label == '20-lines' else base/label
        result['timing'] = {stage:stage_timing(folder/stage/'token-usage.jsonl') for stage in result['usage']}
        result['timing_note'] = 'Baseline total wall time was not instrumented; stage spans are recovered from call timestamps. Later wall_seconds includes matching, new verification and report writing.'
    save(base/'strategy-comparison.json',results)
    lines=['# Full-statement strategy comparison','',
           'All four strategies cover the same 240 bank lines and 181 monetary/claim items. They share the same contextual follow-up on the remaining documents.',
           'These are candidate counts, not accuracy percentages. Strong candidates passed source checks and global allocation checks; none were approved.','',
           '| Strategy | Matching calls | Matching time (s) | Input tokens | Cached input (included) | Output tokens | Raw strong | Checked strong | Tentative | None found |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for label,result in results.items():
        usage=result['usage']['matching']; counts=result['counts']; tokens=usage['totals']
        seconds = f"{result['timing']['matching']['wall_seconds']:.1f}" if usage['attempts'] else 'No model calls'
        lines.append(f"| {label} | {usage['attempts']} | {seconds} | {tokens['input_tokens']:,} | {tokens['cached_input_tokens']:,} | {tokens['output_tokens']:,} | {result['raw_strong']} | {counts.get('strong',0)} | {counts.get('tentative',0)} | {counts.get('none',0)} |")
    lines += ['', 'Source-verification and contextual-review costs are additional and recorded per stage in strategy-comparison.json. Reused source verdicts are recorded as zero-new-token cache hits. Cached input is a subset of reported input, not an additional cost.',
              'The first 20-line run supplies the shared initial source checks and contextual follow-up. Later strategies only make new source-check calls for different proposed allocations. This avoids charging identical evidence review repeatedly, but means total per-strategy verification spend is not a clean isolated-run comparison.',
              'Assembly remains incomplete, aliases and grouped payments can be missed, and model source checks are not independent human ground truth. No-candidate results are not proof that no support exists.',
              'Each strategy directory contains every bank row in statement-matching.csv, saved model inputs/results and durable token events.']
    lines += ['', '## Additional review calls actually made', '',
              '| Strategy | Stage | Calls | Time (s) | Input | Cached input (included) | Output | Unknown usage | Reused verdicts |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    totals = {key:0 for key in FIELDS}
    attempts = unknown = 0
    for label, result in results.items():
        for stage, usage in result['usage'].items():
            tokens = usage['totals']
            attempts += usage['attempts']
            unknown += usage['unknown_attempts']
            for key in FIELDS:
                totals[key] += tokens[key]
            if stage != 'matching':
                seconds = result['timing'][stage]['wall_seconds']
                lines.append(f"| {label} | {stage} | {usage['attempts']} | {seconds:.1f} | {tokens['input_tokens']:,} | {tokens['cached_input_tokens']:,} | {tokens['output_tokens']:,} | {usage['unknown_attempts']} | {usage['cache_hits']} |")
    save(base/'strategy-total-usage.json', {'model':'gpt-5.6-sol','attempts':attempts,
         'unknown_attempts':unknown,'totals':totals})
    lines += ['', f'All experiments combined: {attempts} calls; {unknown} attempts with unknown usage. Reported totals: {json.dumps(totals)}.',
              'Python-only means zero model calls for matching. Its checked counts reuse model source checks and contextual results from the other experiments; it is not an independent model-free validation.']
    outcomes = {}
    for label in results:
        folder = base if label == '20-lines' else base/label
        outcomes[label] = {r['bank_id']:r for r in json.loads((folder/'decisions.json').read_text(encoding='utf-8'))}
    lines += ['', '## Unresolved calls', '']
    for label,result in results.items():
        failed_rows = sum(row['reason'].startswith('Model call unresolved:') for row in outcomes[label].values())
        result['unresolved_matching_lines'] = failed_rows
        lines.append(f"- {label}: {len(result['failed_calls'])} unresolved call results; {failed_rows} bank lines unresolved by matching validation.")
    lines.append('The hybrid run rejected one 20-line response for an unknown or repeated supporting item. These rows remain tentative; this run is not a completed successful match assessment for those 20 lines. The failed attempt and its tokens are retained. No retry was included in this single-run benchmark.')
    save(base/'strategy-comparison.json',results)
    labels = list(results)
    with (base/'strategy-comparison.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['bank_id'] + labels)
        writer.writeheader()
        for bank_id in sorted(outcomes[labels[0]], key=lambda value:int(value[1:])):
            writer.writerow({'bank_id':bank_id, **{label:rows[bank_id]['assessment'] for label,rows in outcomes.items()}})
    model_labels = [label for label in labels if label != 'python-only']
    common = set.intersection(*[{key for key,row in outcomes[label].items() if row['assessment']=='strong'} for label in model_labels])
    identical = [key for key in common if len({signature(outcomes[label][key]) for label in model_labels}) == 1]
    disputed = {key:{label:outcomes[label][key] for label in model_labels}
                for key in outcomes[labels[0]]
                if any(outcomes[label][key]['assessment']=='strong' for label in model_labels)
                and key not in identical}
    save(base/'disputed-strong-candidates.json',disputed)
    lines += ['', f'The three model-assisted matching strategies agree on {len(identical)} strong bank allocations after checks. Agreement is not independent proof of correctness.',
              f'{len(disputed)} other bank lines receive a strong proposal in at least one run but lack agreement on the same strong allocation. Full reasons are in disputed-strong-candidates.json.',
              'The 20/40-line comparison disagrees about returned/retried transfers (B109, B113, B114), incomplete utility-invoice boundaries (B130, B157, B158), and shortened payee identities. These require review; a higher strong count is not proof of greater accuracy.',
              'See strategy-comparison.csv for every bank line side by side.']
    lines += ['', '## Timing method', '',
              'Stage time is the elapsed span from the first call start to the last call finish, including parallel overlap. Per-attempt durations are recorded in strategy-comparison.json. Six parallel workers were used. Cached verdicts make no new call.',
              'The original baseline did not have an end-to-end timer. Its saved stage timestamps do not include Python preparation or pauses between stages. Later strategy totals below include matching, incremental source checks and report writing; they exclude previously shared review work.']
    for label,result in results.items():
        if 'wall_seconds' in result:
            lines.append(f"- {label}: {result['wall_seconds']:.3f} seconds measured end to end.")
    (base/'STRATEGIES.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base',type=Path)
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--report-only',action='store_true')
    args=parser.parse_args()
    if args.report_only:
        write_report(args.base,json.loads((args.base/'strategy-comparison.json').read_text(encoding='utf-8')))
    else:
        compare(args.base,args.workers)
