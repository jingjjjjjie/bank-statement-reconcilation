"""Canonical document and payable-piece facts, with legacy read adapters."""
import calendar
import re
from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import uuid4

from reconciliation.core.prompts import load_schema, piece_types
from reconciliation.core.revision import revision

TEXT = {'type': 'string'}
DEFAULT_CURRENCY = 'MYR'


def model_schema(name):
    """Load a model schema fresh, restricting piece_type to the current kinds headings."""
    schema = load_schema(f'extraction/{name}')
    schema['properties']['pieces']['items']['properties']['piece_type'] = {'type': 'string', 'enum': piece_types()}
    return schema


EXTRACTION = model_schema('extraction')
ASSEMBLY = model_schema('receipt_assembly')
PIECE = EXTRACTION['properties']['pieces']['items']
# Stored typed facts keep any type so older records (invoice, claim_period...) stay valid.
FACTS = {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['type', 'value'],
                                    'properties': {'type': TEXT, 'value': TEXT}}}
TOTALS = EXTRACTION['properties']['totals']


def clean_piece(piece):
    """Apply deterministic clean-ups: positive cents, full dates, default currency."""
    piece = dict(piece)
    try:
        value = Decimal(piece.get('amount', '').replace(',', '').strip())
        piece['amount'] = str(abs(value).quantize(Decimal('0.01'), ROUND_HALF_UP))
    except (InvalidOperation, AttributeError):
        pass  # Non-numeric amounts stay visible for review rather than being guessed.
    month = re.fullmatch(r'(\d{4})-(\d{2})', piece.get('date', ''))
    if month and 1 <= int(month[2]) <= 12:
        year, number = int(month[1]), int(month[2])
        piece['date'] = f'{year:04d}-{number:02d}-{calendar.monthrange(year, number)[1]:02d}'
    currency = piece.get('currency', '').strip().upper()
    piece['currency'] = 'MYR' if currency == 'RM' else currency or DEFAULT_CURRENCY
    piece['currency_default'] = not currency
    return piece


def clean_result(result):
    """Clean every piece and drop zero amounts, noting how many were skipped."""
    if 'pieces' not in result:
        return result
    kept = [clean_piece(p) for p in result.get('pieces', [])]
    zero = [p for p in kept if p['amount'] in ('0.00',)]
    result = {**result, 'pieces': [p for p in kept if p not in zero]}
    if zero:
        result['review_warnings'] = [*result.get('review_warnings', []), f'Skipped {len(zero)} zero-amount piece(s).']
    return result


def canonical(piece):
    """Read new facts or old receipt records without inventing payees or dates."""
    references = deepcopy(piece.get('references', [{'type': 'invoice', 'value': v} for v in piece.get('invoice_numbers', [])]))
    dates = deepcopy(piece.get('dates', []))
    old_number = next((r['value'] for r in references if r.get('type') == 'invoice'), '')
    return {'piece_type': piece.get('piece_type', piece.get('document_type', '')),
        'payer': piece.get('payer', ''), 'payee': piece.get('payee', ''), 'other_names': list(piece.get('other_names', [])),
        'amount': piece.get('amount', piece.get('total', '')), 'currency': piece.get('currency', ''),
        'currency_default': bool(piece.get('currency_default', False)),
        'date': piece.get('date', dates[0]['value'] if dates and isinstance(dates[0], dict) else ''),
        'document_number': piece.get('document_number', old_number),
        'amount_location': piece.get('amount_location', piece.get('location', '')),
        'references': references, 'dates': dates,
        'description': piece.get('description', piece.get('brief_description', '')),
        'amount_basis': piece.get('amount_basis', ''),
        'source_locations': piece.get('source_locations', [piece['location']] if piece.get('location') else []),
        'limitations': piece.get('limitations', [])}


def legacy_piece(piece):
    """Store canonical facts in the editor's record, keeping old accessors for existing consumers."""
    facts = canonical(piece)
    dates = facts['dates'] or ([{'type': 'date', 'value': facts['date']}] if facts['date'] else [])
    result = {'location': facts['amount_location'] or ' | '.join(facts['source_locations']),
        'document_type': facts['piece_type'],
        'invoice_numbers': [facts['document_number']] if facts['document_number'] else
                           [r['value'] for r in facts['references'] if r['type'] == 'invoice'],
        'brief_description': facts['description'], 'total': facts['amount'], 'currency': facts['currency'],
        'limitations': facts['limitations'], 'payee': facts['payee'], 'references': facts['references'],
        'dates': dates, 'amount_basis': facts['amount_basis'], 'payer': facts['payer'],
        'other_names': facts['other_names'], 'date': facts['date'], 'document_number': facts['document_number'],
        'amount_location': facts['amount_location'], 'currency_default': facts['currency_default']}
    for field in ('piece_id', 'source_units', 'needs_review', 'parent_piece_ids'):
        if field in piece:
            result[field] = deepcopy(piece[field])
    return result


def legacy_result(result):
    """Expose old accessors only at legacy boundaries, never request duplicate model prose."""
    if 'pieces' not in result:
        return result
    pieces = [legacy_piece(p) for p in result['pieces']]
    description = result.get('description', result.get('summary', ''))
    return {**{k: v for k, v in result.items() if k != 'pieces'}, 'receipts': pieces, 'brief_description': description,
        'summary': description, 'details': '',
        'document_type': result.get('document_type', ''), 'limitations': result.get('limitations', []),
        'receipt_status': 'receipt' if result.get('document_type') == 'receipt' else 'unsure',
        'supporting_evidence_status': 'potential_support' if pieces else 'uncertain',
        'supporting_evidence_reason': '', 'company': [],
        'parties': list(dict.fromkeys(n for p in pieces for n in [p['payee'], p['payer'], *p['other_names']] if n)),
        'invoice_numbers': list(dict.fromkeys(v for p in pieces for v in p['invoice_numbers'])),
        'references': list(dict.fromkeys(r['value'] for p in pieces for r in p['references'])),
        'dates': list(dict.fromkeys(d['value'] for p in pieces for d in p['dates'])),
        'money': [], 'amounts_and_currencies': [], 'annotations_and_signatures': ''}


def identify(pieces, document_id, unit, source_revision):
    """Give old pieces deterministic identities scoped to their original evidence."""
    return [{**piece, 'piece_id': piece.get('piece_id') or
             'p_' + revision([document_id, unit, source_revision, position])[:24]}
            for position, piece in enumerate(pieces)]


def assign_submitted(pieces, existing):
    """Retain known IDs across edits; assign fresh IDs to explicit additions and splits."""
    known = {p['piece_id']: p for p in existing}
    seen, result = set(), []
    for piece in pieces:
        key = piece.get('piece_id')
        if key and (key not in known or key in seen):
            raise ValueError('Unknown or repeated piece ID; reload before editing')
        parents = piece.get('parent_piece_ids', [])
        inherited = bool(key and parents == known[key].get('parent_piece_ids', []))
        if not isinstance(parents, list) or (not inherited and not set(parents) <= known.keys()):
            raise ValueError('Split or merge refers to an unknown piece')
        key = key or 'p_' + uuid4().hex
        seen.add(key)
        result.append({**piece, 'piece_id': key})
    return result


def merge_all(pieces):
    """Combine a document's edited entries without approving or guessing missing amounts."""
    if not isinstance(pieces, list) or len(pieces) < 2:
        raise ValueError('At least two entries are needed to merge')
    facts = [canonical(piece) for piece in pieces]
    currencies = {('MYR' if p['currency'].upper() == 'RM' else p['currency'].upper()) for p in facts}
    if len(currencies) != 1 or '' in currencies:
        raise ValueError('Set the same currency on every entry before merging')

    def unique(values):
        """Preserve source order and structured values while removing exact duplicates."""
        result = []
        for value in values:
            if value not in ('', None) and value not in result:
                result.append(value)
        return result

    merged = dict(facts[0])
    for field in ('payee', 'payer', 'document_number', 'description', 'amount_location', 'amount_basis'):
        merged[field] = ' / '.join(unique(p[field] for p in facts))
    for field in ('references', 'dates', 'other_names', 'source_locations', 'limitations'):
        merged[field] = unique(value for p in facts for value in p[field])
    for field in ('date', 'piece_type'):
        values = unique(p[field] for p in facts)
        merged[field] = values[0] if len(values) == 1 else ''
    merged['currency'] = next(iter(currencies))
    merged['currency_default'] = any(p['currency_default'] for p in facts)
    complete = all(re.fullmatch(r'\d+(?:\.\d{1,2})?', p['amount']) for p in facts)
    merged['amount'] = format(sum((Decimal(p['amount']) for p in facts), Decimal(0)), '.2f') if complete else ''
    merged['parent_piece_ids'] = unique(value for p in pieces
                                      for value in ([p['piece_id']] if p.get('piece_id') else p.get('parent_piece_ids', [])))
    sources = unique(value for p in pieces for value in p.get('source_units', []))
    if sources:
        merged['source_units'] = sources
    return legacy_piece(merged)
