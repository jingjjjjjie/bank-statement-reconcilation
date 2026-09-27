"""Batched subscription-model matching over ranked candidate pieces."""
import json
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from dashboard import piece_matching
from dashboard.review import write_json
from reconciliation.codex_reviewer import CodexReviewer
from reconciliation.schemas import TEXT, object_schema
from reconciliation.duplicate_workflow import fingerprint
from reconciliation.prompts import load_prompt
from reconciliation.receipt_matching import amount, revision
from reconciliation.currencies import normalize_currency
from reconciliation.review_settings import stage_settings
from reconciliation.vision_workflow import active_config
from reconciliation.match_ranking import rank

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
                if not items[key]['currency'] or normalize_currency(items[key]['currency']) != normalize_currency(banks[row['bank_id']]['currency']):
                    raise ValueError('Matching allocation requires supported matching currencies')
                total += number
        if total > amount(banks[row['bank_id']]['amount']):
            raise ValueError('Matching allocations exceed the bank amount')
        if row['assessment'] == 'strong' and (not used or total != amount(banks[row['bank_id']]['amount'])):
            raise ValueError('Strong proposals require complete supported amounts')
    return rows


def checked_rows(result, keys, allowed, banks, items):
    """Validate each line on its own so one invalid answer cannot discard a whole batch."""
    returned = {}
    for row in result.get('decisions', []):
        if row.get('bank_id') in keys and row['bank_id'] not in returned:
            returned[row['bank_id']] = row
    rows = []
    for key in keys:
        row = returned.get(key)
        if row is None:
            rows.append({'bank_id': key, 'assessment': 'tentative', 'allocations': [],
                         'reason': 'Matching unresolved: the model did not return this line.'})
            continue
        try:
            rows.append(validate_result({'decisions': [row]}, [key], allowed, banks, items)[0])
        except ValueError as error:
            rows.append({'bank_id': key, 'assessment': 'tentative', 'allocations': [],
                         'reason': f'Matching unresolved: {error}. Model said: {row.get("reason", "")}'})
    return rows


def status(review):
    """Report current work and retain failures instead of implying completion."""
    worker = getattr(review, 'piece_match_thread', None)
    saved = getattr(review, 'piece_match_status', {})
    if not saved:
        status_path = review.manifest_path.parent / 'final-review/matching-status.json'
        if status_path.exists():
            saved = json.loads(status_path.read_text(encoding='utf-8'))
    if not saved:
        path = review.manifest_path.parent / 'final-review/piece-suggestions.json'
        if path.exists():
            previous = json.loads(path.read_text(encoding='utf-8'))
            saved = {'completed': len(previous.get('decisions', [])),
                     'total': previous.get('total', len(previous.get('decisions', []))),
                     'failed': len(previous.get('errors', [])), 'error': '\n'.join(previous.get('errors', []))}
    active = getattr(getattr(review, 'piece_match_engine', None), 'active_count', 0)
    running = bool(worker and worker.is_alive()) or bool(active)
    started = saved.get('started_at')
    end = time.time() if running else saved.get('finished_at', saved.get('updated_at', started))
    elapsed = max(0, int(end - started)) if started else None
    return {**saved, 'running': running, 'active_processes': active, 'elapsed_seconds': elapsed,
            'stop_requested': bool(getattr(review, 'piece_match_stopping', saved.get('stop_requested', False)))}


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
    review.piece_match_status = {'completed': 0, 'total': len(banks), 'error': '',
                                 'started_at': time.time(), 'phase': 'Preparing matching'}
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
    finally:
        review.piece_match_status.update(finished_at=time.time(),
                                        stop_requested=bool(getattr(review, 'piece_match_stopping', False)))
        write_json(review.manifest_path.parent / 'final-review/matching-status.json', review.piece_match_status)


BATCH_LINES = 20
PROMPT_LIMIT = 180000


def batches(keys, choices, size=None):
    """Pack lines that share candidate pieces into the same batch, at most `size` lines each."""
    size = size or BATCH_LINES
    parent = {key: key for key in keys}

    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key
    owner = {}
    for key in keys:
        for item_id in choices[key]:
            if item_id in owner:
                parent[root(key)] = root(owner[item_id])
            owner.setdefault(item_id, key)
    groups = {}
    for key in keys:
        groups.setdefault(root(key), []).append(key)
    packed, current = [], []
    # Largest competing groups first; oversized groups are split into consecutive batches.
    for group in sorted(groups.values(), key=len, reverse=True):
        for start in range(0, len(group), size):
            part = group[start:start + size]
            if current and len(current) + len(part) > size:
                packed.append(current)
                current = []
            current = current + part
    if current:
        packed.append(current)
    return packed


def over_allocated(rows, items):
    """Downgrade proposals whose combined allocations exceed a piece's stated amount."""
    used = {}
    for row in rows:
        for allocation in row.get('allocations', []):
            if allocation['amount']:
                used[allocation['item_id']] = used.get(allocation['item_id'], amount('0')) + amount(allocation['amount'])
    over = {key for key, total in used.items() if items[key]['amount'] and total > amount(items[key]['amount'])}
    for row in rows:
        if over & {a['item_id'] for a in row.get('allocations', [])} and 'Competes with another' not in row['reason']:
            row['assessment'] = 'tentative'
            row['reason'] += ' Competes with another bank line for the same evidence; decide in review.'
    return rows


def run_matching(review, binding, banks, items, index, facts, config):
    """Rank candidates in Python, then ask the model about batches of lines; approvals stay human."""
    directory = review.manifest_path.parent / 'final-review'
    (directory / 'piece-matching').mkdir(parents=True, exist_ok=True)
    choices, retrieval = rank(list(banks.values()), items, facts['documents'], index.get('root', ''))
    write_json(directory / 'piece-matching' / 'retrieval.json', retrieval)
    choice = stage_settings(config)['comparison']
    engine = CodexReviewer(directory / 'piece-matching', model=choice['model'], reasoning=choice['reasoning'],
                           timeout=600, cancel_event=review.piece_match_cancel, max_calls=config['max_calls'])
    engine.stage = 'piece_matching'
    review.piece_match_engine = engine
    instructions = load_prompt('matching/matching')
    request_revision = revision([binding, banks, items, index, facts, choice, instructions])
    previous_path = directory / 'piece-suggestions.json'
    previous = json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.exists() else {}
    results = [row for row in previous.get('decisions', [])
               if previous.get('request_revision') == request_revision and row['bank_id'] in banks
               and not row.get('reason', '').startswith('Matching unresolved:')]
    completed = {row['bank_id'] for row in results}
    # Reuse only unchanged, still-verifiable evidence; no model request is needed.
    for keys in batches([key for key in completed if choices[key]], choices):
        piece_matching.model_payload(banks, items, index, facts, choices, keys, retrieval, include_images=False)
    results.extend({'bank_id': key, 'assessment': 'none', 'allocations': [],
                    'reason': 'No amount, name or filename candidate; manual piece search remains available.'}
                   for key in banks if not choices[key] and key not in completed)
    errors = []

    def requests(keys):
        """Build prompts for a batch, halving it until each fits the text limit."""
        supplied, images, allowed = piece_matching.model_payload(
            banks, items, index, facts, choices, keys, retrieval, include_images=False)
        prompt = instructions + '\n' + json.dumps(supplied, ensure_ascii=False, separators=(',', ':'))
        if len(prompt) <= PROMPT_LIMIT:
            return [(keys, supplied, prompt, allowed)]
        if len(keys) == 1:
            raise ValueError('Candidate document text exceeds the matching limit; review manually')
        middle = len(keys) // 2
        return requests(keys[:middle]) + requests(keys[middle:])

    def job(keys):
        """Ask about one batch and validate every returned line against its own candidates."""
        rows = []
        for part, supplied, prompt, allowed in requests(keys):
            if not active_config(index)['codex_enabled']:
                raise ValueError('Codex disabled during matching')
            write_json(directory / 'piece-matching' / f'input-{part[0]}-{len(part)}.json', supplied)
            worker = engine.fork()
            result = worker.ask(prompt, SCHEMA, [])
            try:
                for row in checked_rows(result, part, allowed, banks, items):
                    reasons = retrieval[row['bank_id']].get('reasons', {})
                    # A folder or file name can find evidence but never makes a match strong on its own.
                    if row['assessment'] == 'strong' and row['allocations'] and all(
                            reasons.get(a['item_id'], {}).get('route') == 'found by filename' for a in row['allocations']):
                        row['assessment'] = 'tentative'
                        row['reason'] += ' Linked only through a folder or file name; confirm from the documents.'
                    if retrieval[row['bank_id']]['search_incomplete'] and row['assessment'] == 'none':
                        row['assessment'] = 'tentative'
                        row['reason'] += f" {retrieval[row['bank_id']]['omitted']} further candidates were not shown."
                    rows.append(row)
            except Exception:
                worker.invalidate()
                raise
        return rows

    def publish():
        """Checkpoint proposals after every batch so a stop keeps completed work."""
        write_json(directory / 'piece-suggestions.json', {'binding': binding, 'request_revision': request_revision,
                                                       'total': len(banks), 'decisions': results, 'errors': errors})
        review.piece_match_status = {**getattr(review, 'piece_match_status', {}),
                                    'completed': len(results), 'total': len(banks), 'phase': 'Matching transactions',
                                    'updated_at': time.time(),
                                    'failed': len(errors), 'error': '\n'.join(errors)}
        write_json(directory / 'matching-status.json', review.piece_match_status)

    try:
        publish()
        queue = iter(batches([key for key in banks if choices[key] and key not in completed], choices))
        with ThreadPoolExecutor(max_workers=config['max_parallel']) as pool:
            pending = {}
            for keys in queue:
                pending[pool.submit(job, keys)] = keys
                if len(pending) >= config['max_parallel']:
                    break
            while pending:
                future = next(as_completed(pending))
                keys = pending.pop(future)
                try:
                    results.extend(future.result())
                except Exception as error:
                    errors.append(f'{keys[0]} (+{len(keys) - 1} lines): {error}')
                    results.extend({'bank_id': key, 'assessment': 'tentative', 'allocations': [],
                                    'reason': f'Matching unresolved: {error}'} for key in keys)
                over_allocated(results, items)
                publish()
                keys = None if getattr(review, 'piece_match_stopping', False) else next(queue, None)
                if keys is not None:
                    pending[pool.submit(job, keys)] = keys
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
