"""Structured-output schemas shared by every model backend and workflow stage."""
from reconciliation.prompts import load_schema


def object_schema(properties):
    """Build a strict object: every field required, no extra fields (Codex structured output)."""
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


TEXT = {"type": "string"}
TEXTS = {"type": "array", "items": TEXT}

EXTRACTION = load_schema("extraction/extraction.legacy")
MONEY = EXTRACTION["properties"]["money"]["items"]
RECEIPT = EXTRACTION["properties"]["receipts"]["items"]
from reconciliation.pieces import FACTS, TOTALS  # noqa: E402  (pieces needs prompts loaded first)
# Old saved receipts remain valid; the model uses the lean canonical schema.
RECEIPT['properties'].update({'payee': TEXT, 'references': FACTS, 'dates': FACTS, 'amount_basis': TEXT,
    'piece_id': TEXT, 'parent_piece_ids': TEXTS, 'payer': TEXT, 'other_names': TEXTS, 'date': TEXT,
    'document_number': TEXT, 'amount_location': TEXT, 'currency_default': {'type': 'boolean'}})
EXTRACTION['properties'].update({'summary': TEXT, 'description': TEXT, 'totals': TOTALS, 'review_warnings': TEXTS})

# Legacy duplicate screening and whole-document comparison.
SCREEN = object_schema({"comparisons": {"type": "array", "items": object_schema({
    "right_id": TEXT, "candidate": {"type": "boolean"}, "reason": TEXT,
})}})
COMPARISON = object_schema({
    "classification": {"type": "string", "enum": ["same_document", "revised_or_conflicting",
        "partial_overlap", "related_support", "distinct", "uncertain"]},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    "evidence": TEXTS, "differences": TEXTS, "limitations": TEXTS,
})
