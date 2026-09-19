"""Assemble receipt boundaries across a document while retaining source evidence."""
from jsonschema import validate

from reconciliation.codex_reviewer import RECEIPT, TEXTS, object_schema
from reconciliation.receipt_matching import revision


ASSEMBLED_RECEIPT = object_schema({**RECEIPT["properties"],
    "source_units": {"type": "array", "items": {"type": "integer", "minimum": 1}, "minItems": 1},
    "needs_review": {"type": "boolean"},
})
ASSEMBLED_RECEIPT['required'] = [*RECEIPT['required'], 'source_units', 'needs_review']
ASSEMBLY = object_schema({
    "receipts": {"type": "array", "items": ASSEMBLED_RECEIPT},
    "reviewed_units": {"type": "array", "items": {"type": "integer", "minimum": 1}},
    "limitations": TEXTS,
})
from reconciliation.pieces import TOTALS, TEXT
ASSEMBLY['properties'].update({'summary': TEXT, 'totals': TOTALS, 'document_type': TEXT, 'readable': {'type': 'boolean'}})


def input_revision(document, state):
    """Bind assembly to every page result and original preparation record."""
    return revision([document, [state["units"].get(f"{document['id']}:{n}")
                               for n in range(len(document["units"]))]])


def validate_assembly(value, count):
    """Reject omitted pages and references outside the original document."""
    validate(value, ASSEMBLY)
    # Codex structured output does not support uniqueItems; enforce it locally.
    if len(value["reviewed_units"]) != len(set(value["reviewed_units"])):
        raise ValueError("Receipt assembly repeats a reviewed source unit")
    expected = set(range(1, count + 1))
    if set(value["reviewed_units"]) != expected:
        raise ValueError("Receipt assembly did not review every source unit")
    for receipt in value["receipts"]:
        if len(receipt["source_units"]) != len(set(receipt["source_units"])):
            raise ValueError("Receipt repeats a source unit")
        if not set(receipt["source_units"]) <= expected:
            raise ValueError("Receipt references an unknown source unit")


def current_assembly(document, state):
    """Return only assembly derived from the current page extractions."""
    value = state.get("assemblies", {}).get(document["id"])
    return value if value and value["input_revision"] == input_revision(document, state) else None
