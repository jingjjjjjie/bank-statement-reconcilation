"""Read bounded PDF groups while retaining the original source-unit ledger."""
import json
import re
from pathlib import Path

from reconciliation import pdf_routing
from reconciliation.model_client import MAX_IMAGES, MAX_PROMPT
from reconciliation.pieces import canonical, legacy_result
from reconciliation.prompts import extraction_prompt, load_prompt
from reconciliation.receipt_assembly import input_revision


def whole_request(document, config, state, regenerate=False):
    """Select complete, bounded PDFs without replacing an existing partial extraction."""
    units, digest = document['units'], document['id']
    if (Path(document['paths'][0]).suffix.lower() != '.pdf' or len(units) < 2
            or config['pdf_mode'] in pdf_routing.MODES or any(u.get('blocked') for u in units)):
        return None
    pages = [re.match(r'page (\d+)(?: / part \d+)?$', unit['label']) for unit in units]
    if not all(pages) or len({int(page[1]) for page in pages}) > config['pdf_whole_document_max_pages']:
        return None
    if not regenerate and any(f'{digest}:{n}' in state['units'] for n in range(len(units))):
        return None
    return group_request(document, list(range(1, len(units) + 1)))


def group_request(document, numbers, *, partial=False):
    """Build a bounded request with original unit numbers and page labels."""
    payload, images = [], []
    for number in numbers:
        unit = document['units'][number - 1]
        source = {'source_unit': number, 'location': unit['label'], 'text': unit['text'],
                  'limitation': unit.get('limitation', '')}
        if unit.get('image'):
            images.append(unit['image'])
            source['image_number'] = len(images)
        payload.append(source)
    prompt = extraction_prompt() + '\n\n' + load_prompt('extraction/pdf_document')
    if partial:
        prompt += ('\nThese are only part of a longer PDF. Preserve the supplied original source_unit numbers '
                   'and page labels; do not renumber them. Keep identifiable incomplete pieces with unknown '
                   'amounts empty and flag continuation outside this group. Do not invent document totals. '
                   'A later assembly will inspect all pages and reconcile fragments across groups.\n')
    prompt += '\n' + json.dumps(payload, ensure_ascii=False)
    return (prompt, images) if len(images) <= MAX_IMAGES and len(prompt) <= MAX_PROMPT else None


def chunk_requests(document, config, state, regenerate=False):
    """Group long PDFs by physical pages, preserving completed units on resume."""
    if Path(document['paths'][0]).suffix.lower() != '.pdf' or config['pdf_mode'] in pdf_routing.MODES:
        return
    pages = [re.fullmatch(r'page (\d+)(?: / part \d+)?', unit['label']) for unit in document['units']]
    if not all(pages):
        return
    page_ids = list(dict.fromkeys(int(page[1]) for page in pages))
    limit = config['pdf_whole_document_max_pages']
    if limit < 2 or len(page_ids) <= limit:
        return
    for start in range(0, len(page_ids), limit):
        group = set(page_ids[start:start + limit])
        numbers = [n for n, page in enumerate(pages, 1) if int(page[1]) in group
                   and (regenerate or f"{document['id']}:{n - 1}" not in state['units'])]
        if not numbers or any(document['units'][n - 1].get('blocked') for n in numbers):
            continue
        request = group_request(document, numbers, partial=True)
        if request:
            yield tuple(numbers), *request


def save_chunk(document, state, result, numbers):
    """Checkpoint all group units together; final document assembly remains pending."""
    for number in numbers:
        receipts = [{**canonical(piece), 'source_units': piece['source_units']}
                    for piece in result['receipts'] if min(piece['source_units']) == number]
        state['units'][f"{document['id']}:{number - 1}"] = legacy_result({
            'readable': result.get('readable', True), 'pdf_chunk_units': list(numbers),
            'description': result.get('description', result.get('summary', '')) if number == numbers[0] else '',
            'totals': result.get('totals', []) if number == numbers[0] else [],
            'review_warnings': result.get('review_warnings', []) if number == numbers[0] else [],
            'pieces': receipts})


def save_result(document, state, result):
    """Checkpoint one result with nonduplicating page projections for existing consumers."""
    digest = document['id']
    for number in range(len(document['units'])):
        # A spanning piece belongs to its first source unit in inventory exports only.
        # Human review and matching use the complete document result below.
        pieces = [canonical(piece) for piece in result['receipts'] if min(piece['source_units']) == number + 1]
        state['units'][f'{digest}:{number}'] = legacy_result({
            'readable': result.get('readable', True),
            'description': result.get('description', result.get('summary', '')) if number == 0 else '',
            'totals': result.get('totals', []) if number == 0 else [], 'pieces': pieces})
    state.setdefault('assemblies', {})[digest] = {**result, 'extraction_mode': 'whole_pdf',
        'input_revision': input_revision(document, state)}
