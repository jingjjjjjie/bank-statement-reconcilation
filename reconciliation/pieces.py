"""Canonical document and payable-piece facts, with legacy read adapters."""
from copy import deepcopy
from uuid import uuid4

from reconciliation.receipt_matching import revision
from reconciliation.prompts import load_schema

TEXT = {'type': 'string'}
EXTRACTION = load_schema('extraction')
ASSEMBLY = load_schema('receipt_assembly')
PIECE = EXTRACTION['properties']['pieces']['items']
FACTS = PIECE['properties']['references']
TOTALS = EXTRACTION['properties']['totals']


def canonical(piece):
    """Read new facts or old receipt records without inventing payees or dates."""
    return {'piece_type': piece.get('piece_type', piece.get('document_type', '')),
        'payee': piece.get('payee', ''), 'description': piece.get('description', piece.get('brief_description', '')),
        'references': deepcopy(piece.get('references', [{'type': 'invoice', 'value': v} for v in piece.get('invoice_numbers', [])])),
        'dates': deepcopy(piece.get('dates', [])), 'amount': piece.get('amount', piece.get('total', '')),
        'currency': piece.get('currency', ''), 'amount_basis': piece.get('amount_basis', ''),
        'source_locations': piece.get('source_locations', [piece['location']] if piece.get('location') else []),
        'limitations': piece.get('limitations', [])}


def legacy_piece(piece):
    """Adapt canonical facts to the existing editor while keeping typed metadata."""
    facts = canonical(piece)
    result = {'location': ' | '.join(facts['source_locations']), 'document_type': facts['piece_type'],
        'invoice_numbers': [r['value'] for r in facts['references'] if r['type'] == 'invoice'],
        'brief_description': facts['description'], 'total': facts['amount'], 'currency': facts['currency'],
        'limitations': facts['limitations'], 'payee': facts['payee'], 'references': facts['references'],
        'dates': facts['dates'], 'amount_basis': facts['amount_basis']}
    for field in ('piece_id', 'source_units', 'needs_review', 'parent_piece_ids'):
        if field in piece:
            result[field] = deepcopy(piece[field])
    return result


def legacy_result(result):
    """Expose old accessors only at legacy boundaries, never request duplicate model prose."""
    if 'pieces' not in result:
        return result
    pieces = [legacy_piece(p) for p in result['pieces']]
    return {**{k: v for k, v in result.items() if k != 'pieces'}, 'receipts': pieces, 'brief_description': result['summary'], 'details': '',
        'receipt_status': 'receipt' if result['document_type'] == 'receipt' else 'unsure',
        'supporting_evidence_status': 'potential_support' if pieces else 'uncertain',
        'supporting_evidence_reason': '', 'company': [],
        'parties': list(dict.fromkeys(p['payee'] for p in pieces if p['payee'])),
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
