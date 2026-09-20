"""Live piece evidence for the single final-review allocation ledger."""
from datetime import datetime, timezone
from pathlib import Path
import re

from dashboard.review import write_json
from reconciliation.pieces import canonical
from reconciliation.receipt_matching import revision
from reconciliation.vision_workflow import load_index


def enabled(review):
    """Use live evidence only after an explicit, audited migration."""
    return (review.manifest_path.parent / 'final-review/piece-pipeline.json').exists()


def current(review):
    """Build searchable pieces from current accepted edits and complete document context."""
    from dashboard import receipt_review
    work = review.manifest_path.parent / 'review'
    index, extraction = load_index(work)
    _, saved, units, receipts, bank_rows = receipt_review.context(review)
    if not bank_rows:
        bank_rows = imported_banks(review)
    banks, items = {}, {}
    for n, row in enumerate(bank_rows.values(), 1):
        key = 'B' + str(row.get('sequence') or n)
        if key in banks:
            raise ValueError('Bank sequence IDs must be unique')
        banks[key] = {**row, 'id': key, 'parties': row.get('parties', [row.get('counterparty', '')]),
            'description': row.get('narration', row.get('description', '')), 'date': row.get('date', ''),
            'direction': row.get('direction', 'out'),
            'references': row.get('references', re.findall(r'[A-Za-z0-9-]{5,}', row.get('details_raw', ''))),
            'page': max(0, int(row.get('page') or 1) - 1)}
    if not banks:
        raise ValueError('Prepare the bank statement before matching pieces')
    for receipt in receipts.values():
        facts = canonical(receipt)
        key = receipt['piece_id']
        items[key] = {**facts, 'id': key, 'piece_id': key, 'document': receipt['document_id'],
            'unit': receipt['unit'], 'source_path': receipt['source_path'],
            'filename': Path(receipt['source_path']).name, 'parties': [facts['payee']] if facts['payee'] else [],
            'references': [r['value'] for r in facts['references']], 'typed_references': facts['references'],
            'date': '', 'location': receipt.get('location', ''), 'direction': '',
            'source_cells': [], 'claim_group': '', 'expense_id': '',
            'accepted': receipt['accepted'], 'excluded': False,
            'boundary_unresolved': bool(receipt.get('needs_review')),
            'evidence_revision': revision([receipt['document_id'], facts, receipt.get('source_units', []), receipt['accepted']])}
    documents = {}
    for digest, document in index['documents'].items():
        raw = [extraction['units'].get(f'{digest}:{n}', {}) for n in range(len(document['units']))]
        documents[digest] = {'document_id': digest,
            'summaries': [r.get('summary', r.get('brief_description', '')) for r in raw],
            'totals': [total for r in raw for total in r.get('totals', [])],
            'pieces': [item for item in items.values() if item['document'] == digest]}
    return banks, items, index, {'live_pieces': True, 'documents': documents, 'assembly_count': 1}


def imported_banks(review):
    """Retain a verified existing bank snapshot when its master belongs to a prior run."""
    from dashboard import matching_review
    path = review.manifest_path.parent / 'final-review/bank-import.json'
    if path.exists():
        saved = matching_review.read(path)
        if saved['manifest'] != str(review.manifest_path.resolve()):
            raise ValueError('Imported bank evidence belongs to another workspace')
        return {row['transaction_id']: {**row, 'evidence_revision': revision([
            row, matching_review.source_hash(row['source'])])} for row in saved['banks']}
    if enabled(review):
        return {}
    try:
        _, _, banks, _, _, facts = matching_review.frozen_context(review)
    except (FileNotFoundError, ValueError):
        return {}
    return {bank['transaction_id']: {**bank, 'sequence': key.removeprefix('B'),
        'page': bank['page'] + 1, 'source_sha256': facts['statement_hash'],
        'evidence_revision': revision([facts['bank_hash'], bank, matching_review.source_hash(bank['source'])])}
        for key, bank in banks.items()}


def context(review):
    """Read the shared ledger and retain removed evidence as visibly stale history."""
    from dashboard.matching_review import read
    banks, items, index, facts = current(review)
    path = review.manifest_path.parent / 'final-review/decisions.json'
    state = read(path)
    for decision in state['decisions'].values():
        for entry in decision['allocations']:
            if entry['item_id'] not in items:
                previous = entry.get('item_snapshot') or state.get('historical_items', {}).get(entry['item_id'])
                if previous:
                    items[entry['item_id']] = {**previous, 'retired': True, 'excluded': True}
    # Binding changes with edited evidence; human history and reservations remain intact.
    state['binding'] = revision([banks, items])
    return path, state, banks, items, index, facts


def activate(review):
    """Preserve old decisions explicitly; never promote cached proposals to live approvals."""
    from dashboard import matching_review
    from dashboard.matching_review import read
    if enabled(review):
        return {'activated': True}
    banks, items, index, facts = current(review)
    directory = review.manifest_path.parent / 'final-review'
    path = directory / 'decisions.json'
    old = read(path) if path.exists() else {'version': 0, 'decisions': {}, 'history': []}
    legacy_path = review.manifest_path.parent / 'review/receipt-matches.json'
    legacy = read(legacy_path) if legacy_path.exists() else {'matches': {}}
    if any(m['review_status'] == 'accepted' for m in legacy.get('matches', {}).values()):
        raise ValueError('Undo legacy receipt allocations before migrating to the final ledger; saved approvals were not changed')
    historical = {}
    if old['decisions']:
        _, _, old_banks, historical, _, _ = matching_review.context(review)
        for key in old['decisions']:
            if key not in banks or old_banks[key]['transaction_id'] != banks[key]['transaction_id']:
                raise ValueError('Bank identities changed; preserve the existing ledger and review the bank import')
    bank_import = imported_banks(review) if not (review.manifest_path.parent / 'bank-output/master_statement.csv').exists() else None
    directory.mkdir(parents=True, exist_ok=True)
    if path.exists():
        write_json(directory / ('pre-pieces-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json'), old)
    state = {**old, 'pipeline': 'pieces-v1', 'historical_items': historical,
        'binding': revision([banks, items]), 'version': old['version'] + 1}
    write_json(path, state)
    if bank_import is not None:
        imported = [{k: v for k, v in row.items() if k != 'evidence_revision'} for row in bank_import.values()]
        write_json(directory / 'bank-import.json', {'manifest': str(review.manifest_path.resolve()), 'banks': imported})
    write_json(directory / 'piece-pipeline.json', {'version': 1, 'activated_at': datetime.now(timezone.utc).isoformat(),
        'preserved_decisions': len(old['decisions']), 'policy': 'Historical allocations stay reserved and stale until explicitly reviewed'})
    return {'activated': True, 'preserved_decisions': len(old['decisions'])}


def candidates(banks, items):
    """Shortlist pieces by factual fields without treating amount agreement as approval."""
    from reconciliation.matching_retrieval import retrieve
    return retrieve(list(banks.values()), list(items.values()))[0]


def suggestions(review, banks, items):
    """Use only model suggestions bound to the current bank and complete piece evidence."""
    from dashboard.matching_review import read
    choices = candidates(banks, items)
    path = review.manifest_path.parent / 'final-review/piece-suggestions.json'
    saved = read(path) if path.exists() else {}
    valid = saved.get('binding') == revision([banks, items])
    proposed = {r['bank_id']: {**r, 'saved': True, 'outdated': not valid,
                'failed': r.get('reason', '').startswith('Matching unresolved:')}
                for r in saved.get('decisions', [])}
    result = {key: proposed.get(key, {'bank_id': key, 'assessment': 'none', 'allocations': [],
        'reason': 'No current model proposal. Search pieces or generate matches.'}) for key in banks}
    return choices, result


def model_payload(banks, items, index, facts, choices, selected, retrieval=None):
    """Attach every page and piece of each shortlisted document exactly once per batch."""
    from reconciliation.duplicate_workflow import fingerprint
    documents = {items[key]['document'] for bank in selected for key in choices[bank]}
    context, images = {}, []
    allowed = {}
    for digest in sorted(documents):
        document = index['documents'][digest]
        if fingerprint(Path(document['paths'][0])) != digest:
            raise ValueError('Supporting original changed before matching')
        sources = []
        for unit in document['units']:
            source = {'location': unit['label'], 'text': unit.get('text', '')}
            if unit.get('image'):
                if fingerprint(Path(unit['image'])) != unit['image_sha256']:
                    raise ValueError('Supporting preview changed before matching')
                images.append(unit['image'])
                source['image_number'] = len(images)
            sources.append(source)
        context[digest] = {**facts['documents'][digest], 'sources': sources,
            'pieces': [{k: v for k, v in item.items() if k in {
                'id', 'piece_type', 'payee', 'description', 'typed_references', 'dates',
                'amount', 'currency', 'amount_basis', 'source_locations',
                'boundary_unresolved', 'claim_group', 'expense_id'} and (v or k in {'amount', 'currency'})}
                for item in facts['documents'][digest]['pieces']]}
    for bank in selected:
        bank_documents = {items[key]['document'] for key in choices[bank]}
        allowed[bank] = (list(choices[bank]) if retrieval is not None else
                         [key for key, item in items.items() if item['document'] in bank_documents and not item.get('excluded')])
    bank_fields = ('id', 'amount', 'currency', 'direction', 'date', 'parties', 'references', 'description')
    clean_banks = {key: {field: bank[field] for field in bank_fields if bank.get(field)} for key, bank in banks.items()}
    related = [key for key in banks if key not in selected and
               any(items[item]['document'] in documents for item in choices.get(key, []))]
    payload = {'banks': [{**clean_banks[key], 'candidate_ids': allowed[key]} for key in selected],
        'documents': context, 'related_bank_entries': [clean_banks[key] for key in related],
        'retrieval': {key: retrieval[key] for key in selected} if retrieval else {}}
    return payload, images, allowed
