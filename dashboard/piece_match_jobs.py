"""Bounded subscription-model matching over complete documents and persistent pieces."""
import json
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from dashboard import piece_matching
from dashboard.review import write_json
from reconciliation.codex_reviewer import CodexReviewer, TEXT, object_schema
from reconciliation.duplicate_workflow import fingerprint
from reconciliation.prompts import load_prompt
from reconciliation.receipt_matching import amount
from reconciliation.review_settings import stage_settings
from reconciliation.vision_workflow import active_config
from reconciliation.matching_retrieval import retrieve

SCHEMA = object_schema({'decisions': {'type': 'array', 'items': object_schema({
    'bank_id': TEXT, 'assessment': {'type': 'string', 'enum': ['strong', 'tentative', 'none']},
    'allocations': {'type': 'array', 'items': object_schema({'item_id': TEXT, 'amount': TEXT})}, 'reason': TEXT})}})


def validate_result(result, keys, allowed, banks, items):
    """Reject fabricated IDs, repeated pieces, missing banks and unsupported allocations."""
    rows = result['decisions']
    if len(rows) != len(keys) or {r['bank_id'] for r in rows} != set(keys):
        raise ValueError('Matching response omitted or repeated bank entries')
    for row in rows:
        if row['assessment'] == 'none' and row['allocations']:
            raise ValueError('A no-match response cannot allocate pieces')
        used, total = set(), amount('0')
        for allocation in row['allocations']:
            key, value = allocation['item_id'], allocation['amount']
            if key in used or key not in allowed[row['bank_id']]:
                raise ValueError('Matching response contains an unknown or repeated piece')
            used.add(key)
            if value:
                number = amount(value)
                if not items[key]['amount'] or number <= 0 or number > amount(items[key]['amount']):
                    raise ValueError('Matching allocation exceeds the stated piece amount')
                if not items[key]['currency'] or items[key]['currency'] != banks[row['bank_id']]['currency']:
                    raise ValueError('Matching allocation requires supported matching currencies')
                total += number
        if total > amount(banks[row['bank_id']]['amount']):
            raise ValueError('Matching allocations exceed the bank amount')
        if row['assessment'] == 'strong' and (not used or total != amount(banks[row['bank_id']]['amount'])):
            raise ValueError('Strong proposals require complete supported amounts')
    return rows


def status(review):
    """Report current work and retain failures instead of implying completion."""
    worker = getattr(review, 'piece_match_thread', None)
    saved = getattr(review, 'piece_match_status', {})
    if not saved:
        path = review.manifest_path.parent / 'final-review/piece-suggestions.json'
        if path.exists():
            previous = json.loads(path.read_text(encoding='utf-8'))
            saved = {'completed': len(previous.get('decisions', [])),
                     'total': previous.get('total', len(previous.get('decisions', []))),
                     'failed': len(previous.get('errors', [])), 'error': '\n'.join(previous.get('errors', []))}
    active = getattr(getattr(review, 'piece_match_engine', None), 'active_count', 0)
    return {**saved, 'running': bool(worker and worker.is_alive()) or bool(active), 'active_processes': active,
            'stop_requested': bool(getattr(review, 'piece_match_stopping', False))}


def start(review):
    """Start one bounded model run without holding the HTTP decision lock."""
    from dashboard.content_review import execution_status
    if status(review)['running']:
        return status(review)
    if execution_status(review)['running']:
        raise ValueError('Wait for extraction to finish before generating matches')
    if not piece_matching.enabled(review):
        piece_matching.activate(review)
    _, state, banks, items, index, facts = piece_matching.context(review)
    if any(fingerprint(Path(bank['source'])) != bank['source_sha256'].upper() for bank in banks.values()):
        raise ValueError('Bank evidence changed; refresh the statement before matching')
    config = active_config(index)
    if not config['codex_enabled']:
        raise ValueError('Enable Codex before generating matches')
    review.piece_match_status = {'completed': 0, 'total': len(banks), 'error': ''}
    review.piece_match_stopping = False
    review.piece_match_cancel = threading.Event()
    review.piece_match_engine = None
    review.piece_match_thread = threading.Thread(target=run, args=(review, state['binding'], banks, items, index, facts, config), daemon=True)
    review.piece_match_thread.start()
    return status(review)


def run(review, binding, banks, items, index, facts, config):
    """Keep setup failures visible as well as individual model-call failures."""
    try:
        run_matching(review, binding, banks, items, index, facts, config)
    except Exception as error:
        review.piece_match_status['error'] = str(error)


def run_matching(review, binding, banks, items, index, facts, config):
    """Checkpoint each response with token accounting; approvals remain exclusively human."""
    directory = review.manifest_path.parent / 'final-review'
    (directory / 'piece-matching').mkdir(parents=True, exist_ok=True)
    choices, retrieval = retrieve(list(banks.values()), list(items.values()))
    write_json(directory / 'piece-matching' / 'retrieval.json', retrieval)
    choice = stage_settings(config)['comparison']
    engine = CodexReviewer(directory / 'piece-matching', model=choice['model'], reasoning=choice['reasoning'],
                           timeout=600, cancel_event=review.piece_match_cancel, max_calls=config['max_calls'])
    engine.stage = 'piece_matching'
    review.piece_match_engine = engine
    results, errors = [], []

    def job(key):
        """Provide full shortlisted documents; never silently truncate source evidence."""
        if not choices[key]:
            return {'bank_id': key, 'assessment': 'none', 'allocations': [], 'reason': 'No indexed candidate; manual piece search remains available.'}
        supplied, images, allowed = piece_matching.model_payload(banks, items, index, facts, choices, [key], retrieval)
        prompt = load_prompt('matching_policy') + '\n\n' + load_prompt('piece_matching') + '\n' + json.dumps(supplied, ensure_ascii=False, separators=(',', ':'))
        if len(images) > 40 or len(prompt) > 180000:
            raise ValueError('Complete document context exceeds the matching limit; review manually')
        if not active_config(index)['codex_enabled']:
            raise ValueError('Codex disabled during matching')
        write_json(directory / 'piece-matching' / f'input-{key}.json', supplied)
        worker = engine.fork()
        result = worker.ask(prompt, SCHEMA, images)
        try:
            row = validate_result(result, [key], allowed, banks, items)[0]
            if retrieval[key]['search_incomplete']:
                row['reason'] += f" Search limited: {retrieval[key]['omitted']} eligible pieces were not shortlisted."
                if row['assessment'] == 'none' or retrieval[key]['reference_overflow']:
                    row['assessment'] = 'tentative'
            return row
        except Exception:
            worker.invalidate()
            raise

    try:
        keys = iter(banks)
        # Keep the pending work bounded, refilling immediately when one bank finishes.
        with ThreadPoolExecutor(max_workers=config['max_parallel']) as pool:
            pending = {}
            for _ in range(config['max_parallel']):
                key = next(keys, None)
                if key is not None:
                    pending[pool.submit(job, key)] = key
            while pending:
                future = next(as_completed(pending))
                key = pending.pop(future)
                try:
                    results.append(future.result())
                except Exception as error:
                    errors.append(f'{key}: {error}')
                    results.append({'bank_id': key, 'assessment': 'tentative', 'allocations': [], 'reason': f'Matching unresolved: {error}'})
                write_json(directory / 'piece-suggestions.json', {'binding': binding, 'total': len(banks), 'decisions': results, 'errors': errors})
                review.piece_match_status = {'completed': len(results), 'total': len(banks),
                                            'failed': len(errors), 'error': '\n'.join(errors)}
                key = None if getattr(review, 'piece_match_stopping', False) else next(keys, None)
                if key is not None:
                    pending[pool.submit(job, key)] = key
    except Exception as error:
        review.piece_match_status['error'] = str(error)


def stop(review):
    """Cancel active subscription processes and leave completed proposals checkpointed."""
    review.piece_match_stopping = True
    event = getattr(review, 'piece_match_cancel', None)
    if event:
        event.set()
    engine = getattr(review, 'piece_match_engine', None)
    if engine:
        engine.cancel()
    return status(review)
