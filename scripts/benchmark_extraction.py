"""Benchmark fresh extraction at increasing concurrency without altering review state."""
import argparse
import hashlib
import json
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


def save(path, value):
    """Atomically publish benchmark progress and results."""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def digest(path):
    """Hash exact input bytes without loading the entire file into memory."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(root, work, output):
    """Freeze code, prompts and prepared units, preserving source provenance."""
    output.mkdir(parents=True, exist_ok=False)
    runtime = output / 'runtime'
    runtime.mkdir()
    for name in ('reconciliation', 'prompts'):
        shutil.copytree(root / name, runtime / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    index = json.loads((work / 'index.json').read_text(encoding='utf-8-sig'))
    tasks, excluded, sources = [], [], []
    assets = output / 'assets'
    assets.mkdir()
    started = time.perf_counter()
    for key, document in index['documents'].items():
        source = Path(document['paths'][0])
        if digest(source) != key.lower():
            raise ValueError(f'Source changed: {source}')
        sources.append({'id': key, 'paths': document['paths'],
                        'original_paths': document.get('original_paths', document['paths'])})
        if document.get('error') or not document.get('accepted', True):
            excluded.append({'document': key, 'reason': document.get('error') or 'unsupported'})
            continue
        for number, unit in enumerate(document['units']):
            task = {'id': f'{key}-{number}', 'document': key, 'number': number,
                    'source': str(source), 'label': unit['label'], 'text': unit['text'],
                    'limitation': unit.get('limitation', ''), 'image': None}
            if unit.get('blocked'):
                excluded.append({'unit': task['id'], 'reason': 'blocked input'})
                continue
            if unit.get('image'):
                image = Path(unit['image'])
                fingerprint = digest(image)
                if fingerprint != unit['image_sha256'].lower():
                    raise ValueError(f'Prepared image changed: {image}')
                target = assets / (task['id'] + image.suffix)
                shutil.copyfile(image, target)
                task.update(image=str(target), image_sha256=fingerprint)
            tasks.append(task)
    manifest = {'source_index': str(work / 'index.json'), 'source_index_sha256': digest(work / 'index.json'),
                'sources': sources, 'tasks': tasks, 'excluded': excluded,
                'snapshot_seconds': time.perf_counter() - started,
                'runtime_hashes': {str(p.relative_to(runtime)): digest(p) for p in runtime.rglob('*') if p.is_file()}}
    save(output / 'inputs.json', manifest)
    return manifest


def run_level(output, tasks, workers):
    """Run every unit with uncached responses and the production Codex wrapper."""
    from reconciliation.codex_reviewer import CodexReviewer, EXTRACTION
    from reconciliation.prompts import load_prompt
    from reconciliation.review_settings import document_stage
    from reconciliation.token_usage import summary

    folder = output / f'workers-{workers}'
    folder.mkdir(exist_ok=False)
    engine = CodexReviewer(folder, model='gpt-5.6-sol', max_calls=len(tasks), timeout=240)
    prompt = load_prompt('extraction')
    results = []
    started = time.perf_counter()
    save(folder / 'progress.json', {'status': 'running', 'workers': workers, 'total': len(tasks), 'completed': 0})

    def job(task):
        """Measure one validated extraction and retain failures as unresolved."""
        begin = time.perf_counter()
        worker = engine.fork()
        worker.stage = document_stage(task['source'])
        # Per-unit namespaces also prevent identical units from hitting a local cache.
        worker.cache = folder / 'model-cache' / task['id']
        worker.cache.mkdir(parents=True)
        result = {'unit': task['id'], 'document': task['document'], 'stage': worker.stage,
                  'started_offset_seconds': begin - started}
        try:
            request = prompt + '\n' + json.dumps({'location': task['label'], 'text': task['text'],
                         'limitation': task['limitation']}, ensure_ascii=False)
            response = worker.ask(request, EXTRACTION, [task['image']] if task['image'] else [])
            result.update(status='finished' if response['readable'] else 'unresolved',
                          readable=response['readable'])
        except Exception as error:
            result.update(status='unresolved', error=f'{type(error).__name__}: {error}')
        result['elapsed_seconds'] = time.perf_counter() - begin
        result['finished_offset_seconds'] = time.perf_counter() - started
        return result

    # Refill a freed slot immediately, like the production scheduler.
    remaining = iter(tasks)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(job, task) for task in [next(remaining, None) for _ in range(workers)] if task}
        while pending:
            future = next(as_completed(pending))
            pending.remove(future)
            result = future.result()
            results.append(result)
            with (folder / 'unit-results.jsonl').open('a', encoding='utf-8') as log:
                log.write(json.dumps(result) + '\n')
            save(folder / 'progress.json', {'status': 'running', 'workers': workers, 'total': len(tasks),
                 'completed': len(results), 'elapsed_seconds': time.perf_counter() - started,
                 'statuses': dict(Counter(row['status'] for row in results))})
            task = next(remaining, None)
            if task is not None:
                pending.add(pool.submit(job, task))
            if len(results) % 20 == 0 or len(results) == len(tasks):
                print(f'{workers} workers: {len(results)}/{len(tasks)} units, {time.perf_counter() - started:.1f}s', flush=True)
    elapsed = time.perf_counter() - started
    durations = sorted(row['elapsed_seconds'] for row in results)
    successful = sum(row['status'] == 'finished' for row in results)
    report = {'workers': workers, 'units': len(tasks), 'documents': len({t['document'] for t in tasks}),
              'elapsed_seconds': elapsed, 'statuses': dict(Counter(row['status'] for row in results)),
              'successful_units_per_minute': successful * 60 / elapsed,
              'latency_seconds': {'mean': mean(durations), 'median': median(durations),
                                  'p90': durations[max(0, (len(durations) * 9 + 9) // 10 - 1)], 'max': max(durations)},
              'tokens': summary(folder / 'token-usage.jsonl')}
    report['tokens']['complete'] = report['tokens']['unknown_attempts'] == 0
    save(folder / 'report.json', report)
    save(folder / 'progress.json', {**report, 'status': 'complete'})
    print(json.dumps(report), flush=True)
    return report


def main():
    """Execute the planned levels against identical frozen extraction inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', nargs='+', type=int, default=[8, 12, 16])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not args.work.is_absolute() or not args.output.is_absolute():
        parser.error('Use absolute work and output paths')
    if any(count < 1 for count in args.workers) or len(set(args.workers)) != len(args.workers):
        parser.error('Worker levels must be positive and unique')
    manifest = prepare(root, args.work, args.output)
    save(args.output / 'plan.json', {'workers': args.workers, 'model': 'gpt-5.6-sol', 'reasoning': 'default',
         'timeout_seconds': 240, 'cache': 'disabled per unit and per level',
         'scope': 'Fresh model extraction of all prepared units; local document rendering reused. No screening or matching.',
         'started_utc': datetime.now(timezone.utc).isoformat()})
    sys.path.insert(0, str(args.output / 'runtime'))
    from reconciliation import development_cache
    # Disable sharing only inside this benchmark process; dashboard settings are untouched.
    development_cache.root_for = lambda path: None
    reports = []
    while len(reports) < len(json.loads((args.output / 'plan.json').read_text())['workers']):
        workers = json.loads((args.output / 'plan.json').read_text())['workers'][len(reports)]
        reports.append(run_level(args.output, manifest['tasks'], workers))
        save(args.output / 'results.json', reports)
    print('BENCHMARK COMPLETE', flush=True)


if __name__ == '__main__':
    main()
