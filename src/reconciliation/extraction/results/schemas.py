"""Structured-output schemas shared by every model backend and workflow stage."""

from reconciliation.core.prompts import load_schema
from reconciliation.extraction.results.pieces import FACTS, TOTALS


def object_schema(properties):
    """Build a strict object: every field required, no extra fields (Codex structured output)."""
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


TEXT = {"type": "string"}
TEXTS = {"type": "array", "items": TEXT}

EXTRACTION = load_schema("extraction/extraction.legacy")
RECEIPT = EXTRACTION["properties"]["receipts"]["items"]
# Old saved receipts remain valid; the model uses the lean canonical schema.
RECEIPT['properties'].update(
    {
        'payee': TEXT,
        'references': FACTS,
        'dates': FACTS,
        'amount_basis': TEXT,
        'piece_id': TEXT,
        'parent_piece_ids': TEXTS,
        'payer': TEXT,
        'other_names': TEXTS,
        'date': TEXT,
        'document_number': TEXT,
        'amount_location': TEXT,
        'currency_default': {'type': 'boolean'},
    }
)
EXTRACTION['properties'].update({'summary': TEXT, 'description': TEXT, 'totals': TOTALS, 'review_warnings': TEXTS})
