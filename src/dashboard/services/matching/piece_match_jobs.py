"""Batched subscription-model matching over ranked candidate pieces."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dashboard.services.matching import piece_matching
from dashboard.services.review import write_json
from reconciliation.core.money import amount, normalize_currency
from reconciliation.core.prompts import load_prompt
from reconciliation.core.revision import revision
from reconciliation.core.settings import stage_settings
from reconciliation.extraction.results.schemas import TEXT, object_schema
from reconciliation.extraction.workflow import active_config
from reconciliation.intake.duplicates import fingerprint
from reconciliation.matching.ranking import rank
from reconciliation.model.codex import CodexReviewer

SCHEMA = object_schema(
    {
        'decisions': {
            'type': 'array',
            'items': object_schema(
                {
                    'bank_id': TEXT,
                    'assessment': {'type': 'string', 'enum': ['strong', 'tentative', 'none']},
                    'allocations': {'type': 'array', 'items': object_schema({'item_id': TEXT, 'amount': TEXT})},
                    'reason': TEXT,
                }
            ),
        }
    }
)

#: Seconds one matching batch call may run; batches are larger than single-document extraction calls.
MATCHING_CALL_TIMEOUT = 600


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
                if not items[key]['currency'] or normalize_currency(items[key]['currency']) != normalize_currency(
                    banks[row['bank_id']]['currency']
                ):
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
            rows.append(
                {
                    'bank_id': key,
                    'assessment': 'tentative',
                    'allocations': [],
                    'reason': 'Matching unresolved: the model did not return this line.',
                }
            )
            continue
        # "None" with attached pieces (e.g. a returned transfer) keeps the evidence for review instead of failing.
        if row.get('assessment') == 'none' and row.get('allocations'):
            row = {**row, 'assessment': 'tentative', 'reason': f'{row.get("reason", "")} Model said none; review.'}
        try:
            rows.append(validate_result({'decisions': [row]}, [key], allowed, banks, items)[0])
        except ValueError as error:
            rows.append(
                {
                    'bank_id': key,
                    'assessment': 'tentative',
                    'allocations': [],
                    'reason': f'Matching unresolved: {error}. Model said: {row.get("reason", "")}',
                }
            )
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
            saved = {
                'completed': len(previous.get('decisions', [])),
                'total': previous.get('total', len(previous.get('decisions', []))),
                'failed': len(previous.get('errors', [])),
                'error': '\n'.join(previous.get('errors', [])),
            }
    active = getattr(getattr(review, 'piece_match_engine', None), 'active_count', 0)
    running = bool(worker and worker.is_alive()) or bool(active)
    started = saved.get('started_at')
    end = time.time() if running else saved.get('finished_at', saved.get('updated_at', started))
    elapsed = max(0, int(end - started)) if started else None
    outdated = False
    proposals = review.manifest_path.parent / 'final-review/piece-suggestions.json'
    if not running and proposals.exists() and piece_matching.enabled(review):
        previous = json.loads(proposals.read_text(encoding='utf-8'))
        saved = {**saved, 'failed': sum(failed_row(row) for row in previous.get('decisions', []))}
        outdated = matching_outdated(review, previous)
    return {
        **saved,
        'running': running,
        'outdated': outdated,
        'active_processes': active,
        'elapsed_seconds': elapsed,
        'stop_requested': bool(getattr(review, 'piece_match_stopping', saved.get('stop_requested', False))),
    }


def matching_outdated(review, previous):
    """Cache display freshness only; saves and model reuse still verify original bytes."""
    from dashboard.services.live_state import signature

    try:
        index_path = review.manifest_path.parent / 'review/index.json'
        index = json.loads(index_path.read_text(encoding='utf-8'))
        config = active_config(index)
        instructions = load_prompt('matching/matching')
        key = revision([signature(review), stage_settings(config)['comparison'], instructions])
        cached = getattr(review, 'piece_match_freshness', {})
        if cached.get('key') != key or time.monotonic() - cached.get('checked', 0) >= 60:
            _, state, banks, items, index, facts = piece_matching.context(review)
            cached = {
                'key': key,
                'checked': time.monotonic(),
                'revision': request_revision(
                    state['binding'], banks, items, index, facts, config, instructions=instructions
                ),
            }
            review.piece_match_freshness = cached
        return previous.get('request_revision') != cached['revision']
    except (OSError, ValueError, KeyError):
        return True  # Unavailable evidence cannot certify an old run as current.


def start(review, mode="resume", confirmation=None):
    """Start one bounded model run without holding the HTTP decision lock."""
    from dashboard.services.extraction.extraction_runs import execution_status

    if mode not in {'resume', 'regenerate', 'retry_failed'}:
        raise ValueError('Choose a valid matching action')
    if status(review)['running']:
        return status(review)
    if execution_status(review)['running']:
        raise ValueError('Wait for extraction to finish before generating matches')
    if not piece_matching.enabled(review):
        if mode != 'resume':
            raise ValueError('Load for final matching before retrying or regenerating')
        piece_matching.activate(review)
    ledger, state, banks, items, index, facts = piece_matching.context(review)
    if any(fingerprint(Path(bank['source'])) != bank['source_sha256'].upper() for bank in banks.values()):
        raise ValueError('Bank evidence changed; refresh the statement before matching')
    config = active_config(index)
    if not config['codex_enabled']:
        raise ValueError('Enable Codex before generating matches')
    directory = review.manifest_path.parent / 'final-review'
    proposals = directory / 'piece-suggestions.json'
    previous = json.loads(proposals.read_text(encoding='utf-8')) if proposals.exists() else {}
    if mode == 'retry_failed':
        if previous.get('request_revision') != request_revision(state['binding'], banks, items, index, facts, config):
            raise ValueError('Matching inputs changed. Regenerate matches instead of retrying failed results.')
        if not any(failed_row(row) for row in previous.get('decisions', [])):
            raise ValueError('There are no failed matches to retry')
    if mode == 'regenerate':
        confirmation = confirmation or {}
        if (
            confirmation.get('confirm_clear') is not True
            or confirmation.get('binding') != state['binding']
            or confirmation.get('version') != state['version']
        ):
            raise ValueError('Refresh and confirm regeneration before clearing supporting decisions')
        for digest, document in index['documents'].items():
            if fingerprint(Path(document['paths'][0])) != digest:
                raise ValueError('Supporting evidence changed; refresh extraction before regenerating')
        generation = uuid4().hex
        (directory / 'backups').mkdir(exist_ok=True)
        write_json(directory / 'backups' / f'regenerate-{generation}.json', {'ledger': state, 'proposals': previous})
        at = datetime.now(timezone.utc).isoformat()
        for bank_id, decision in state['decisions'].items():
            state['history'].append(
                {
                    'bank_id': bank_id,
                    'action': 'regenerate',
                    'at': at,
                    'reviewer': 'Local user',
                    'before': decision,
                    'after': None,
                    'note': 'Cleared supporting decisions for confirmed regeneration.',
                }
            )
        state['decisions'] = {}
        state['version'] += 1
        write_json(ledger, state)
        # Clearing historical allocations can remove retired pieces from the current binding.
        ledger, state, banks, items, index, facts = piece_matching.context(review)
        write_json(ledger, state)
        write_json(
            proposals,
            {'binding': state['binding'], 'generation': generation, 'decisions': [], 'total': len(banks), 'errors': []},
        )
    review.piece_match_status = {
        'completed': 0,
        'total': len(banks),
        'error': '',
        'started_at': time.time(),
        'phase': 'Preparing matching',
    }
    review.piece_match_stopping = False
    review.piece_match_cancel = threading.Event()
    review.piece_match_engine = None
    review.piece_match_thread = threading.Thread(
        target=run, args=(review, state['binding'], banks, items, index, facts, config, mode), daemon=True
    )
    review.piece_match_thread.start()
    return status(review)


def run(review, binding, banks, items, index, facts, config, mode="resume"):
    """Keep setup failures visible as well as individual model-call failures."""
    try:
        run_matching(review, binding, banks, items, index, facts, config, mode)
    except Exception as error:
        review.piece_match_status['error'] = str(error)
    finally:
        review.piece_match_status.update(
            finished_at=time.time(), stop_requested=bool(getattr(review, 'piece_match_stopping', False))
        )
        write_json(review.manifest_path.parent / 'final-review/matching-status.json', review.piece_match_status)


BATCH_LINES = 20
PROMPT_LIMIT = 180000
TOP_CANDIDATES = 3  # Lines compete when they share one of their top-ranked candidates.
PACKING_MARGIN = 5000  # Characters left for JSON keys and wrappers not counted by batch_inputs().


def batches(keys, choices, documents=None, measure=None, size=None, limit=None):
    """Pack competing lines together and group lines that need the same documents, so each is sent fewer times.

    Args:
        keys: Bank lines to ask about, in bank order.
        choices: Ranked candidate piece IDs per line.
        documents: Document IDs behind each line's candidates; defaults to the candidates themselves.
        measure: Prompt characters a list of lines needs; defaults to zero.
        size: Most lines per batch. limit: most characters per batch (requests() still halves as a backstop).
    """
    size, limit = size or BATCH_LINES, limit or PROMPT_LIMIT
    documents = documents or {key: set(choices[key]) for key in keys}
    measure = measure or (lambda lines: 0)
    order = {key: number for number, key in enumerate(keys)}
    parent = {key: key for key in keys}

    def root(key):
        """Find the group representative."""
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    owner = {}
    for key in keys:
        for item_id in choices[key][:TOP_CANDIDATES]:
            if item_id in owner:
                parent[root(key)] = root(owner[item_id])
            owner.setdefault(item_id, key)
    groups = {}
    for key in keys:
        groups.setdefault(root(key), []).append(key)

    def held(lines):
        """Documents a batch of lines needs."""
        return set().union(*(documents[key] for key in lines))

    def fits(lines):
        """Whether the lines and their documents stay within both limits."""
        return len(lines) <= size and measure(lines) <= limit

    # Oversized groups split by their best candidate, then into consecutive chunks that fit.
    units = []
    for group in groups.values():
        parts = [group]
        if not fits(group):
            by_best = {}
            for key in group:
                by_best.setdefault(choices[key][0], []).append(key)
            parts = list(by_best.values())
        for part in parts:
            chunk = []
            for key in part:
                if chunk and not fits(chunk + [key]):
                    units.append(chunk)
                    chunk = []
                chunk.append(key)
            units.append(chunk)
    # Start with the largest unit, then add units sharing most documents and bringing fewest new ones.
    remaining = sorted(units, key=lambda unit: (-len(unit), order[unit[0]]))
    packed = []
    while remaining:
        current = remaining.pop(0)
        while True:
            have = held(current)
            ranked = sorted(
                remaining, key=lambda unit: (-len(have & held(unit)), len(held(unit) - have), order[unit[0]])
            )
            pick = next((unit for unit in ranked if fits(current + unit)), None)
            if pick is None:
                break
            remaining.remove(pick)
            current = current + pick
        packed.append(current)
    return packed


def batch_inputs(keys, choices, items, index, facts, retrieval, banks):
    """Documents behind each line, and a measure of the prompt characters a list of lines needs, for batches()."""
    documents = {key: {items[item_id]['document'] for item_id in choices[key]} for key in keys}

    def chars(value):
        """Characters the value adds to the compact JSON prompt."""
        return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str))

    users = {}  # Bank lines whose candidates use each document; the others are sent as related context.
    for key, ids in choices.items():
        for digest in {items[item_id]['document'] for item_id in ids}:
            users.setdefault(digest, set()).add(key)
    needed = set().union(*documents.values())
    view = {digest: chars(piece_matching.document_view(digest, index, facts)) for digest in needed}
    bank = {key: chars(piece_matching.bank_view(banks[key])) for key in set().union(*(users[d] for d in needed))}
    line = {key: chars([piece_matching.bank_view(banks[key]), choices[key], retrieval.get(key, {})]) for key in keys}

    def measure(lines):
        """Characters for these lines, their documents and the related bank lines those documents bring."""
        held = set().union(*(documents[key] for key in lines))
        related = set().union(*(users[d] for d in held)) - set(lines)
        return sum(view[d] for d in held) + sum(line[k] for k in lines) + sum(bank[k] for k in related)

    return documents, measure


def over_allocated(rows, items):
    """Downgrade proposals whose combined allocations exceed a piece's stated amount."""
    used = {}
    for row in rows:
        for allocation in row.get('allocations', []):
            if allocation['amount']:
                used[allocation['item_id']] = used.get(allocation['item_id'], amount('0')) + amount(
                    allocation['amount']
                )
    over = {key for key, total in used.items() if items[key]['amount'] and total > amount(items[key]['amount'])}
    for row in rows:
        if over & {a['item_id'] for a in row.get('allocations', [])} and 'Competes with another' not in row['reason']:
            row['assessment'] = 'tentative'
            row['reason'] += ' Competes with another bank line for the same evidence; decide in review.'
    return rows


def request_revision(binding, banks, items, index, facts, config, *, instructions=None):
    """Bind matching progress and resumable proposals to evidence, settings and prompt."""
    choice = stage_settings(config)['comparison']
    instructions = load_prompt('matching/matching') if instructions is None else instructions
    return revision([binding, banks, items, index, facts, choice, instructions])


def failed_row(row):
    """Identify failed lines separately from valid tentative or no-match proposals."""
    return row.get('reason', '').startswith('Matching unresolved:')


def run_matching(review, binding, banks, items, index, facts, config, mode="resume"):
    """Rank candidates in Python, then ask the model about batches of lines; approvals stay human."""
    directory = review.manifest_path.parent / 'final-review'
    (directory / 'piece-matching').mkdir(parents=True, exist_ok=True)
    choices, retrieval = rank(list(banks.values()), items, facts['documents'], index.get('root', ''))
    write_json(directory / 'piece-matching' / 'retrieval.json', retrieval)
    choice = stage_settings(config)['comparison']
    engine = CodexReviewer(
        directory / 'piece-matching',
        model=choice['model'],
        reasoning=choice['reasoning'],
        timeout=MATCHING_CALL_TIMEOUT,
        cancel_event=review.piece_match_cancel,
        max_calls=config['max_calls'],
    )
    engine.stage = 'piece_matching'
    review.piece_match_engine = engine
    instructions = load_prompt('matching/matching')
    current_revision = request_revision(binding, banks, items, index, facts, config, instructions=instructions)
    previous_path = directory / 'piece-suggestions.json'
    previous = json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.exists() else {}
    results = [
        row
        for row in previous.get('decisions', [])
        if previous.get('request_revision') == current_revision and row['bank_id'] in banks and not failed_row(row)
    ]
    completed = {row['bank_id'] for row in results}
    targets = (
        {row['bank_id'] for row in previous.get('decisions', []) if failed_row(row)}
        if mode == 'retry_failed'
        else set(banks) - completed
    )
    generation = previous.get('generation', '')
    attempt = uuid4().hex if mode == 'retry_failed' else ''

    # Reuse only unchanged, still-verifiable evidence; no model request is needed.
    def packed(keys):
        """Batches for these lines, packed by competition and shared documents."""
        documents, measure = batch_inputs(keys, choices, items, index, facts, retrieval, banks)
        return batches(keys, choices, documents, measure, limit=PROMPT_LIMIT - len(instructions) - PACKING_MARGIN)

    for keys in packed([key for key in completed if choices[key]]):
        piece_matching.model_payload(banks, items, index, facts, choices, keys, retrieval, include_images=False)
    results.extend(
        {
            'bank_id': key,
            'assessment': 'none',
            'allocations': [],
            'reason': 'No amount, name or filename candidate; manual piece search remains available.',
        }
        for key in banks
        if not choices[key] and key in targets
    )
    errors = []

    def requests(keys):
        """Build prompts for a batch, halving it until each fits the text limit."""
        supplied, images, allowed = piece_matching.model_payload(
            banks, items, index, facts, choices, keys, retrieval, include_images=False
        )
        if generation or attempt:
            supplied = {**supplied, 'matching_run': generation, 'retry_attempt': attempt}
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
                    if (
                        row['assessment'] == 'strong'
                        and row['allocations']
                        and all(
                            reasons.get(a['item_id'], {}).get('route') == 'found by filename'
                            for a in row['allocations']
                        )
                    ):
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
        write_json(
            directory / 'piece-suggestions.json',
            {
                'binding': binding,
                'request_revision': current_revision,
                'generation': generation,
                'total': len(banks),
                'decisions': results,
                'errors': errors,
            },
        )
        review.piece_match_status = {
            **getattr(review, 'piece_match_status', {}),
            'completed': len(results),
            'total': len(banks),
            'phase': 'Matching transactions',
            'updated_at': time.time(),
            'failed': sum(failed_row(row) for row in results),
            'error': '\n'.join(errors),
        }
        write_json(directory / 'matching-status.json', review.piece_match_status)

    try:
        publish()
        queue = iter(packed([key for key in banks if choices[key] and key in targets]))
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
                    results.extend(
                        {
                            'bank_id': key,
                            'assessment': 'tentative',
                            'allocations': [],
                            'reason': f'Matching unresolved: {error}',
                        }
                        for key in keys
                    )
                # Retried proposals may be downgraded; successful saved results remain unchanged.
                if mode == 'retry_failed':
                    checked = over_allocated([dict(row) for row in results], items)
                    results[:] = [old if old['bank_id'] in completed else new for old, new in zip(results, checked)]
                else:
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
