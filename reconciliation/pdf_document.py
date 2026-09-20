"""Read small PDFs together while retaining the existing review and source-unit ledger."""
import json
import re
from pathlib import Path

from reconciliation import pdf_routing
from reconciliation.pieces import canonical, legacy_result
from reconciliation.prompts import load_prompt
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
    payload, images = [], []
    for number, unit in enumerate(units, 1):
        source = {'source_unit': number, 'location': unit['label'], 'text': unit['text'],
                  'limitation': unit.get('limitation', '')}
        if unit.get('image'):
            images.append(unit['image'])
            source['image_number'] = len(images)
        payload.append(source)
    prompt = load_prompt('extraction') + '\n' + load_prompt('pdf_document') + '\n' + json.dumps(payload, ensure_ascii=False)
    return (prompt, images) if len(images) <= 40 and len(prompt) <= 100000 else None


def save_result(document, state, result):
    """Checkpoint one result with nonduplicating page projections for existing consumers."""
    digest = document['id']
    for number in range(len(document['units'])):
        # A spanning piece belongs to its first source unit in inventory exports only.
        # Human review and matching use the complete document result below.
        pieces = [canonical(piece) for piece in result['receipts'] if min(piece['source_units']) == number + 1]
        state['units'][f'{digest}:{number}'] = legacy_result({
            'readable': result.get('readable', True),
            'summary': result.get('summary', '') if number == 0 else '',
            'totals': result.get('totals', []) if number == 0 else [], 'pieces': pieces})
    state.setdefault('assemblies', {})[digest] = {**result, 'extraction_mode': 'whole_pdf',
        'input_revision': input_revision(document, state)}
