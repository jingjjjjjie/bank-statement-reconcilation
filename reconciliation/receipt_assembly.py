"""Assemble receipt boundaries across a document while retaining source evidence."""
from jsonschema import validate

from reconciliation.codex_reviewer import RECEIPT, TEXTS, object_schema
from reconciliation.receipt_matching import revision


ASSEMBLED_RECEIPT = object_schema({**RECEIPT["properties"],
    "source_units": {"type": "array", "items": {"type": "integer", "minimum": 1}, "minItems": 1,
                     "uniqueItems": True},
    "needs_review": {"type": "boolean"},
})
ASSEMBLY = object_schema({
    "receipts": {"type": "array", "items": ASSEMBLED_RECEIPT},
    "reviewed_units": {"type": "array", "items": {"type": "integer", "minimum": 1}, "uniqueItems": True},
    "limitations": TEXTS,
})


def input_revision(document, state):
    """Bind assembly to every page result and original preparation record."""
    return revision([document, [state["units"].get(f"{document['id']}:{n}")
                               for n in range(len(document["units"]))]])


def validate_assembly(value, count):
    """Reject omitted pages and references outside the original document."""
    validate(value, ASSEMBLY)
    expected = set(range(1, count + 1))
    if set(value["reviewed_units"]) != expected:
        raise ValueError("Receipt assembly did not review every source unit")
    for receipt in value["receipts"]:
        if not set(receipt["source_units"]) <= expected:
            raise ValueError("Receipt references an unknown source unit")


def current_assembly(document, state):
    """Return only assembly derived from the current page extractions."""
    value = state.get("assemblies", {}).get(document["id"])
    return value if value and value["input_revision"] == input_revision(document, state) else None
