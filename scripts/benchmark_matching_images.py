"""Regenerate isolated extraction, then compare final matching with and without images."""
import argparse
import copy
import hashlib
import json
import random
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


def read(path):
    """Read a saved UTF-8 artifact."""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, data):
    """Publish a complete artifact atomically without touching live review state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def digest(path):
    """Bind frozen evidence to its exact bytes."""
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def no_shared_cache(path):
    """Keep benchmark responses outside application response caches."""
    return None


def extraction_coverage(index, state):
    """Count complete documents and keep missing or stale assembly unresolved."""
    from reconciliation.receipt_assembly import current_assembly
    complete, unresolved = [], []
    for key, document in index['documents'].items():
        if not document.get('accepted', True):
            continue
        ready = not document.get('error') and bool(document['units']) and all(
            f'{key}:{n}' in state.get('units', {}) for n in range(len(document['units'])))
        if ready and len(document['units']) > 1:
            ready = current_assembly(document, state) is not None
        (complete if ready else unresolved).append(key)
    return {'complete_documents': len(complete), 'eligible_documents': len(complete) + len(unresolved),
            'unresolved_documents': unresolved}


def prepare(project, output, workers):
    """Freeze current bank evidence and all supporting extraction inputs."""
    from dashboard.review import Review
    from dashboard.piece_matching import current
    from reconciliation.review_settings import load_config
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=False)
    review = Review(project / 'duplicate-manifest.json', project / 'dashboard-data')
    queue = project / 'review/regeneration.json'
    jobs = read(queue).get('jobs', {}) if queue.exists() else {}
    with patch('dashboard.regeneration.snapshot', return_value=jobs):
        banks, old_items, index, old_facts = current(review)
    save(output / 'previous-evidence.json', {'banks': banks, 'items': old_items, 'facts': old_facts})
    save(output / 'previous-suggestions.json', read(project / 'final-review/piece-suggestions.json'))
    save(output / 'previous-decisions.json', read(project / 'final-review/decisions.json'))
    config = load_config(review.config_path)
    config.update(max_parallel=workers, model='gpt-5.6-sol', reasoning='default', codex_enabled=True)
    for choice in config.get('stages', {}).values():
        choice.update(model='gpt-5.6-sol', reasoning='default')
    config_path = output / 'config.json'
    save(config_path, config)
    frozen = copy.deepcopy(index)
    frozen.update(config=config, config_path=str(config_path))
    ledger = read(project / 'review/receipt-matches.json')
    for key, document in frozen['documents'].items():
        source = Path(document['paths'][0])
        if digest(source) != key.lower():
            raise ValueError('Source changed: ' + str(source))
        folder = output / 'sources' / key
        folder.mkdir(parents=True)
        target = folder / ('source' + source.suffix.lower())
        shutil.copyfile(source, target)
        document['prepared_paths'] = document['paths']
        document['paths'] = [str(target)]
        if key in ledger.get('trash', {}):
            document['accepted'] = False
        for n, unit in enumerate(document['units'], 1):
            if unit.get('image'):
                image = Path(unit['image'])
                if digest(image) != unit['image_sha256'].lower():
                    raise ValueError('Prepared image changed')
                destination = folder / f'page-{n}.png'
                shutil.copyfile(image, destination)
                unit['image'] = str(destination)
    save(output / 'extraction/index.json', frozen)
    save(output / 'extraction/state.json', {'index_sha256': digest(output / 'extraction/index.json').upper(),
         'units': {}, 'screens': {}, 'pairs': {}, 'decisions': {}, 'model': None})
    for name in ['reconciliation', 'prompts', 'dashboard']:
        shutil.copytree(root / name, output / 'runtime' / name,
            ignore=shutil.ignore_patterns('__pycache__', 'node_modules', 'frontend', '.data'))
    save(output / 'plan.json', {'model': 'gpt-5.6-sol', 'workers': workers, 'seed': 20260927,
        'document_count': len(frozen['documents']),
        'eligible_documents': sum(d.get('accepted', True) and not d.get('error') for d in frozen['documents'].values()),
        'arms': ['images', 'text'], 'matching_cases': 50,
        'scope': 'Fresh extraction with clarified RM/MYR rule, then paired matching on identical facts; no live approvals or matches written.',
        'code_hashes': {str(p.relative_to(output / 'runtime')): digest(p)
                        for p in (output / 'runtime').rglob('*') if p.is_file()},
        'live_index_hash': digest(project / 'review/index.json'),
        'live_state_hash': digest(project / 'review/state.json'),
        'live_accepted_hash': digest(project / 'review/receipt-matches.json')})
    print(json.dumps({k: v for k, v in read(output / 'plan.json').items() if k != 'code_hashes'}), flush=True)


def extract_fresh(output, workers):
    """Run the production extraction and assembly pipeline against frozen inputs."""
    from reconciliation.codex_reviewer import CodexReviewer
    from reconciliation.vision_workflow import load, run
    from reconciliation.token_usage import summary
    work = output / 'extraction'
    config = read(output / 'config.json')
    config['max_parallel'] = workers
    save(output / 'config.json', config)
    index, state = load(work)
    engine = CodexReviewer(work, model='gpt-5.6-sol', max_calls=1000, timeout=300)
    started = time.perf_counter()
    status, error = 'finished', None
    with patch('reconciliation.development_cache.root_for', no_shared_cache):
        try:
            run(work, index, state, engine, extraction_only=True)
        except Exception as failure:
            status, error = 'unresolved', str(failure)
    result = {'status': status, 'error': error, 'seconds': time.perf_counter() - started,
              'usage': summary(engine.usage_path), 'unit_results': len(state['units']),
              'assemblies': len(state.get('assemblies', {})), **extraction_coverage(index, state)}
    if result['unresolved_documents']:
        result['status'] = 'unresolved'
    save(output / 'extraction-summary.json', result)
    with (output / 'extraction-runs.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({**result, 'workers': workers, 'new_attempts': engine.calls}) + '\n')
    print(json.dumps({key: value for key, value in result.items()
                      if key != 'unresolved_documents'}), flush=True)
    return result


def extract_with_retries(output, workers, retries):
    """Resume saved work after capacity failures with bounded delayed retries."""
    stalled, previous = 0, None
    for attempt in range(retries + 1):
        audit = output / 'extraction/token-usage.jsonl'
        offset = len(audit.read_text(encoding='utf-8').splitlines()) if audit.exists() else 0
        result = extract_fresh(output, workers)
        if result['status'] == 'finished' or attempt == retries:
            return result
        events = [json.loads(line) for line in audit.read_text(encoding='utf-8').splitlines()[offset:]] if audit.exists() else []
        failures = [event for event in events if event.get('status') == 'failed']
        if not failures or not failures[-1].get('events'):
            return result
        event_path = Path(failures[-1]['events'])
        if not event_path.exists() or 'Selected model is at capacity' not in event_path.read_text(encoding='utf-8'):
            return result
        progress = (result['unit_results'], result['assemblies'])
        stalled = stalled + 1 if progress == previous else 0
        if stalled >= 2:
            return result
        previous = progress
        print(f'Capacity retry {attempt + 1}/{retries} in 30 seconds; saved progress retained.', flush=True)
        time.sleep(30)
    return result


def build_facts(output):
    """Represent fresh extractions as unapproved benchmark pieces with stable IDs."""
    from reconciliation.pieces import canonical
    from reconciliation.receipt_assembly import current_assembly
    from reconciliation.receipt_matching import revision
    from reconciliation.currencies import normalize_currencies
    index, state = read(output / 'extraction/index.json'), read(output / 'extraction/state.json')
    banks = read(output / 'previous-evidence.json')['banks']
    items, documents, unresolved = {}, {}, []
    for key, document in index['documents'].items():
        if not document.get('accepted', True) or document.get('error'):
            continue
        raw = (current_assembly(document, state) if len(document['units']) > 1
               else state['units'].get(key + ':0'))
        if raw is None:
            unresolved.append(key)
            continue
        doc_items = []
        for n, piece in enumerate(raw.get('receipts', [])):
            fact = canonical(piece)
            item_id = 'bench_' + revision([key, fact, n])[:24]
            item = {**fact, 'id': item_id, 'piece_id': item_id, 'document': key,
                    'source_path': document['paths'][0], 'parties': [fact['payee']] if fact['payee'] else [],
                    'references': [r['value'] for r in fact['references']], 'typed_references': fact['references'],
                    'date': '', 'direction': '', 'claim_group': '', 'expense_id': '',
                    'accepted': False, 'excluded': False, 'boundary_unresolved': not raw.get('readable', True)}
            items[item_id] = item
            doc_items.append(item)
        documents[key] = {'document_id': key, 'summaries': [raw.get('summary', '')],
                          'totals': raw.get('totals', []), 'pieces': doc_items}
    value = normalize_currencies({'banks': banks, 'items': items, 'index': index,
                                 'facts': {'documents': documents}, 'unresolved_documents': unresolved})
    save(output / 'fresh-evidence.json', value)
    return value


def prepare_cases(output):
    """Freeze stratified bank cases and identical extracted facts for both arms."""
    from dashboard.piece_matching import model_payload
    from reconciliation.matching_retrieval import retrieve
    from reconciliation.prompts import load_prompt
    coverage = extraction_coverage(read(output / 'extraction/index.json'), read(output / 'extraction/state.json'))
    if coverage['unresolved_documents']:
        raise ValueError('Finish fresh extraction before selecting matching cases: '
                         + str(len(coverage['unresolved_documents'])) + ' documents unresolved')
    evidence = build_facts(output)
    banks, items = evidence['banks'], evidence['items']
    choices, retrieval = retrieve(list(banks.values()), list(items.values()))
    prior = read(output / 'previous-suggestions.json')
    errors = {entry.split(': ', 1)[0]: entry.split(': ', 1)[1] for entry in prior.get('errors', [])}
    groups = {'currency': [], 'size': [], 'other': []}
    for key in sorted(banks, key=lambda value: int(value[1:])):
        label = 'currency' if 'matching currencies' in errors.get(key, '') else 'size' if 'matching limit' in errors.get(key, '') else 'other'
        if choices[key]:
            groups[label].append(key)
    rng = random.Random(20260927)
    selected = []
    for group, count in [('currency', 15), ('size', 10), ('other', 25)]:
        rng.shuffle(groups[group])
        selected.extend((key, group) for key in groups[group][:count])
    used = {key for key, _ in selected}
    for key in sorted(banks):
        if len(selected) >= 50:
            break
        if key not in used and choices[key]:
            selected.append((key, 'fill'))
    rng.shuffle(selected)
    cases = []
    for number, (key, group) in enumerate(selected, 1):
        payload, images, allowed = model_payload(banks, items, evidence['index'], evidence['facts'], choices, [key], retrieval)
        # Both prompts truthfully describe optional images; all accounting rules stay identical.
        # This historical comparison keeps the prompt text it was measured with.
        instructions = load_prompt('legacy/matching_policy') + '\n\n' + load_prompt('legacy/piece_matching')
        instructions = instructions.replace('supplied complete supporting documents and their pieces',
            'supplied extracted supporting-document facts and their pieces')
        instructions += ('\nEvidence mode is stated in the payload. Use attached images only when supplied. '
                         'Without images, do not claim to have inspected visuals. Missing, ambiguous or conflicting '
                         'extracted facts remain unknown and require tentative or context-only treatment. '
                         'Never fill a blank extracted currency from the bank currency.\n')
        cases.append({'number': number, 'bank_id': key, 'stratum': group, 'payload': payload,
                      'images': images, 'allowed': allowed, 'instructions': instructions,
                      'retrieval': retrieval[key]})
    save(output / 'cases.json', cases)
    print(json.dumps({'cases': len(cases), 'strata': dict(Counter(c['stratum'] for c in cases)),
          'images_over_limit': sum(len(c['images']) > 40 for c in cases),
          'fresh_pieces': len(items), 'blank_currency_pieces': sum(not i['currency'] for i in items.values()),
          'unresolved_documents': evidence['unresolved_documents']}), flush=True)
    return cases, evidence


def match(output, workers):
    """Compare image-backed and text-only calls with the same strict validation."""
    from dashboard.piece_match_jobs import SCHEMA, validate_result
    from reconciliation.codex_reviewer import CodexReviewer
    from reconciliation.token_usage import summary
    cases, evidence = prepare_cases(output) if not (output / 'cases.json').exists() else (read(output / 'cases.json'), read(output / 'fresh-evidence.json'))

    def job(case, arm):
        """Measure one arm and retain app limits or invalid proposals as unresolved."""
        folder = output / 'matching' / arm / case['bank_id']
        if (folder / 'measurement.json').exists():
            return read(folder / 'measurement.json')
        payload = copy.deepcopy(case['payload'])
        payload['evidence_mode'] = 'extracted facts plus attached page images' if arm == 'images' else 'extracted facts and native text only; no page images attached'
        images = case['images'] if arm == 'images' else []
        if arm == 'text':
            for doc in payload['documents'].values():
                for source in doc['sources']:
                    source.pop('image_number', None)
        prompt = case['instructions'] + json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        save(folder / 'request.json', {'prompt': prompt, 'images': images, 'schema': SCHEMA})
        row = {'bank_id': case['bank_id'], 'arm': arm, 'stratum': case['stratum'],
               'image_count': len(images), 'prompt_characters': len(prompt)}
        engine = CodexReviewer(folder, model='gpt-5.6-sol', max_calls=1, timeout=600)
        engine.stage = 'matching_' + arm
        started = time.perf_counter()
        try:
            if len(images) > 40 or len(prompt) > 180000:
                raise ValueError('Complete document context exceeds the matching limit; review manually')
            response = engine.ask(prompt, SCHEMA, images)
            row['raw_response'] = response
            decision = validate_result(response, [case['bank_id']], case['allowed'], evidence['banks'], evidence['items'])[0]
            if case['retrieval']['search_incomplete']:
                if decision['assessment'] == 'none' or case['retrieval']['reference_overflow']:
                    decision['assessment'] = 'tentative'
                decision['reason'] += ' Search incomplete; omitted candidates remain unresolved.'
            row.update(status='finished', decision=decision)
        except Exception as error:
            row.update(status='unresolved', error=str(error))
        row.update(seconds=time.perf_counter() - started, usage=summary(engine.usage_path))
        save(folder / 'measurement.json', row)
        return row

    results, started = [], time.perf_counter()
    with patch('reconciliation.development_cache.root_for', no_shared_cache), ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(job, case, arm) for case in cases
                   for arm in (['images', 'text'] if case['number'] % 2 else ['text', 'images'])]
        for future in as_completed(futures):
            results.append(future.result())
            save(output / 'matching-progress.json', {'completed': len(results), 'total': len(futures),
                'seconds': time.perf_counter() - started, 'statuses': dict(Counter(r['status'] for r in results))})
            if len(results) % 10 == 0:
                print(f'Matching {len(results)}/{len(futures)}', flush=True)
    save(output / 'matching-results.json', results)


def main():
    """Run one explicit benchmark stage, with production settings kept unchanged."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'extract', 'cases', 'match'])
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--capacity-retries', type=int, default=0)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error('Use one to eight workers')
    if not 0 <= args.capacity_retries <= 20:
        parser.error('Use zero to twenty capacity retries')
    output = args.output.resolve()
    if args.stage == 'prepare':
        prepare(args.project.resolve(), output, args.workers)
        return
    sys.path.insert(0, str(output / 'runtime'))
    for name, expected in read(output / 'plan.json')['code_hashes'].items():
        if digest(output / 'runtime' / name) != expected:
            raise ValueError('Frozen runtime changed: ' + name)
    if args.stage == 'extract':
        extract_with_retries(output, args.workers, args.capacity_retries)
    elif args.stage == 'cases':
        prepare_cases(output)
    else:
        match(output, args.workers)


if __name__ == '__main__':
    main()
