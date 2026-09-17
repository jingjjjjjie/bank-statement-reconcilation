"""Compare fresh native-text and vision calls without changing customer review state."""
import argparse
import json
import time
import hashlib
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pymupdf

from reconciliation.codex_reviewer import CodexReviewer
from reconciliation.development_cache import write_json
from reconciliation.document_reader import extract
from reconciliation.duplicate_workflow import fingerprint
from reconciliation.pdf_routing import extract_unit, inspect_page
from reconciliation.review_settings import DEFAULTS
from reconciliation.token_usage import summary


def main():
    """Sample native and risky pages and checkpoint every completed comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pages', type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.pages <= 20:
        parser.error('--pages must be between 1 and 20')
    args.output.mkdir(parents=True, exist_ok=False)
    index = json.loads(args.index.read_text(encoding='utf-8'))
    eligible, risky = [], []
    reasons = Counter()
    for digest, doc in index['documents'].items():
        path = Path(doc['paths'][0])
        if path.suffix.lower() != '.pdf' or doc.get('error'):
            continue
        if fingerprint(path).lower() != digest.lower():
            raise ValueError('Source changed: ' + str(path))
        with pymupdf.open(path) as pdf:
            for n, page in enumerate(pdf):
                probe = inspect_page(page)
                reasons.update(probe['reasons'])
                (risky if probe['reasons'] else eligible).append((path, n, digest))
    # Prefer distinct documents to avoid filling the sample from one long PDF.
    native = list(dict((str(p), (p, n, d)) for p, n, d in reversed(eligible)).values())
    selected = (native[:max(1, args.pages - 2)] + risky[:2])[:args.pages]
    write_json(args.output / 'plan.json', {'eligible_pages': len(eligible), 'risky_pages': len(risky),
        'reasons': dict(reasons), 'sample': [(str(p), n + 1, d) for p, n, d in selected],
        'model': 'gpt-5.6-sol', 'cache': 'local results fresh; shared cache disabled; provider caching still applies',
        'code_hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                        for root in ('reconciliation', 'prompts') for p in Path(root).glob('*') if p.is_file()},
        'scope': 'Page extraction only. No assembly, matching, acceptance or source modifications.'})
    engine = CodexReviewer(args.output, model='gpt-5.6-sol', max_calls=2 * len(selected), timeout=240)
    rows = []
    with patch('reconciliation.development_cache.root_for', return_value=None), \
         patch('reconciliation.pdf_routing.mode', return_value={'enabled': True}):
        for i, (path, number, digest) in enumerate(selected):
            start = time.perf_counter()
            # Extract the original PDF normally; choose precisely the sampled page.
            units = extract(path, args.output / 'assets' / str(i), {**DEFAULTS, 'pdf_mode': 'compare'})
            unit = next(u for u in units if u['label'] == f'page {number + 1} / part 1')
            timings = {}
            route_usage = {}

            def ask(prompt, schema, images=(), stage='pdf'):
                """Track each route separately using the existing subscription wrapper."""
                worker = engine.fork()
                worker.stage = stage
                begin = time.perf_counter()
                before = summary(engine.usage_path)['totals']
                try:
                    return worker.ask(prompt, schema, images)
                finally:
                    timings[stage] = time.perf_counter() - begin
                    after = summary(engine.usage_path)
                    route_usage[stage] = {k: after['totals'][k] - v for k, v in before.items()}
                    route_usage[stage]['cumulative_unknown_attempts'] = after['unknown_attempts']

            row = {'source': str(path), 'page': number + 1, 'sha256': digest}
            try:
                extract_unit(unit, ask, 'compare', args.output / f'page-{i}.json', set())
                audit = json.loads((args.output / f'page-{i}.json').read_text())
                row.update(status='finished', reasons=audit['reasons'], agreement=audit.get('critical_fields_agree'))
            except Exception as error:
                row.update(status='unresolved', error=str(error))
            row.update(seconds=time.perf_counter() - start, route_seconds=timings, route_usage=route_usage)
            rows.append(row)
            usage = summary(args.output / 'token-usage.jsonl')
            write_json(args.output / 'report.json', {'pages': rows, 'usage': usage,
                'usage_complete': usage['unknown_attempts'] == 0, 'human_verified_accuracy': None})
            print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
