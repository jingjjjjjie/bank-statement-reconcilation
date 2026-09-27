"""Report measured matching outcomes without treating agreement as ground truth."""

import argparse
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from statistics import median

from reconciliation.model.token_usage import summarize
from scripts.benchmark_matching_images import read, save


def event_path(value):
    """Resolve container event paths when reporting from the Windows checkout."""
    path = Path(value)
    if not path.exists() and value.startswith('/workspace/'):
        path = Path(__file__).resolve().parents[1] / value.removeprefix('/workspace/')
    return path


def aggregate(paths):
    """Total durable attempts and price only usage with verified cache-write data."""
    events = [
        json.loads(line) for path in paths if path.exists() for line in path.read_text(encoding='utf-8').splitlines()
    ]
    result = summarize(events)
    attempts = {event['id']: event for event in events if event.get('id')}
    priced, cost, writes = 0, 0.0, 0
    for event in attempts.values():
        usage = event.get('usage')
        if not usage or not event.get('events'):
            continue
        path = event_path(event['events'])
        if not path.exists():
            continue
        turns = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        completed = [turn['usage'] for turn in turns if turn.get('type') == 'turn.completed']
        if not completed or 'cache_write_input_tokens' not in completed[-1]:
            continue
        write = completed[-1]['cache_write_input_tokens']
        uncached = usage['input_tokens'] - usage['cached_input_tokens'] - write
        if uncached < 0:
            raise ValueError('Cache accounting exceeds reported input')
        long = usage['input_tokens'] > 272000
        cost += (
            (uncached * 4 + usage['cached_input_tokens'] * 0.4 + write * 5) * (2 if long else 1)
            + usage['output_tokens'] * (30 if long else 20)
        ) / 1e6
        priced += 1
        writes += write
    result.update(
        api_equivalent_usd_known=cost,
        priced_attempts=priced,
        api_equivalent_complete=priced == len(attempts),
        cache_write_input_tokens=writes,
    )
    return result


def allocation_key(row):
    """Compare allocation identities and decimal values independently of ordering."""
    return sorted(
        (a['item_id'], str(Decimal(a['amount']).normalize()) if a['amount'] else '')
        for a in row['decision']['allocations']
    )


def report(output):
    """Write full and paired comparisons, exposing all failures and unknown usage."""
    rows = read(output / 'matching-results.json')
    evidence = read(output / 'fresh-evidence.json')
    pairs = {}
    for row in rows:
        pairs.setdefault(row['bank_id'], {})[row['arm']] = row
    attempted = {
        key
        for key, pair in pairs.items()
        if len(pair) == 2 and all(row['usage']['attempts'] > 0 for row in pair.values())
    }
    valid = {
        key
        for key, pair in pairs.items()
        if len(pair) == 2 and all(row['status'] == 'finished' for row in pair.values())
    }
    result = {
        'arms': {},
        'common_attempted_pairs': len(attempted),
        'valid_pairs': len(valid),
        'extraction': aggregate([output / 'extraction/token-usage.jsonl']),
        'note': 'Agreement is not accuracy. No independent ground truth was supplied.',
        'pricing': {
            'basis': 'Standard API-equivalent estimate, not a subscription charge',
            'source': 'https://developers.openai.com/api/docs/models/gpt-5.6-sol',
            'checked': '2026-09-27',
        },
    }
    for arm in ['images', 'text']:
        selected = [row for row in rows if row['arm'] == arm]
        paths = [output / 'matching' / arm / row['bank_id'] / 'token-usage.jsonl' for row in selected]
        durations = [row['seconds'] for row in selected if row['usage']['attempts']]
        result['arms'][arm] = {
            'statuses': dict(Counter(row['status'] for row in selected)),
            'errors': dict(Counter(row['error'] for row in selected if row.get('error'))),
            'assessments': dict(Counter(row['decision']['assessment'] for row in selected if 'decision' in row)),
            'usage': aggregate(paths),
            'common_attempted_usage': aggregate([path for path in paths if path.parent.name in attempted]),
            'valid_paired_usage': aggregate([path for path in paths if path.parent.name in valid]),
            'median_attempt_seconds': median(durations) if durations else 0,
        }
    result['paired'] = [
        {
            'bank_id': key,
            'same_assessment': pair['images']['decision']['assessment'] == pair['text']['decision']['assessment'],
            'same_allocations': allocation_key(pair['images']) == allocation_key(pair['text']),
            'images': pair['images']['decision'],
            'text': pair['text']['decision'],
        }
        for key, pair in pairs.items()
        if key in valid
    ]
    result['assessment_agreement'] = sum(pair['same_assessment'] for pair in result['paired'])
    result['allocation_agreement'] = sum(pair['same_allocations'] for pair in result['paired'])
    save(output / 'benchmark-report.json', result)
    lines = [
        '# Matching images benchmark',
        '',
        f"Fresh extraction: {len(evidence['facts']['documents'])} documents, {len(evidence['items'])} pieces. "
        'Both arms use the same fresh facts and native text. '
        'Only the image arm attaches page images. Model: gpt-5.6-sol, original coding instructions.',
        '',
        '| Metric | Images | Text only |',
        '|---|---:|---:|',
    ]
    a, b = result['arms']['images'], result['arms']['text']
    metrics = [
        ('Validated responses', a['statuses'].get('finished', 0), b['statuses'].get('finished', 0)),
        ('Unresolved', a['statuses'].get('unresolved', 0), b['statuses'].get('unresolved', 0)),
        ('Median attempted seconds', round(a['median_attempt_seconds'], 2), round(b['median_attempt_seconds'], 2)),
    ]
    for scope, title in [('usage', 'All cases'), ('common_attempted_usage', 'Common attempted cases')]:
        for field in ['input_tokens', 'cached_input_tokens', 'output_tokens']:
            metrics.append((title + ' ' + field, a[scope]['totals'][field], b[scope]['totals'][field]))
        metrics += [
            (title + ' unknown-usage attempts', a[scope]['unknown_attempts'], b[scope]['unknown_attempts']),
            (
                title + ' known API-equivalent USD',
                round(a[scope]['api_equivalent_usd_known'], 6),
                round(b[scope]['api_equivalent_usd_known'], 6),
            ),
        ]
    lines += [f'| {label} | {left} | {right} |' for label, left, right in metrics]
    lines += [
        '',
        f"Common attempted pairs: {len(attempted)}. Valid pairs: {len(valid)}. "
        f"Assessment agreement: {result['assessment_agreement']}/{len(valid)}. "
        f"Allocation agreement: {result['allocation_agreement']}/{len(valid)}.",
        '',
        'Agreement is not accuracy; neither arm is an independently verified reference. '
        'Context-limit blocks and model failures remain unresolved. Unknown usage is excluded from known totals. '
        'Reasoning is included in output; cached input is included in input.',
        '',
        'These are subscription calls, not a paid API connection. Dollar figures are standard API-equivalent '
        'estimates using [official rates](https://developers.openai.com/api/docs/models/gpt-5.6-sol), checked '
        'September 27, 2026. Unknown or unpriced attempts make cost totals incomplete. '
        'Extraction is shared preprocessing and is separately recorded in benchmark-report.json.',
    ]
    (output / 'benchmark-report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'paired'}, indent=2))


def main():
    """Report one completed benchmark without issuing model calls."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    report(parser.parse_args().output)


if __name__ == '__main__':
    main()
