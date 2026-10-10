"""Load editable workflow instructions and schemas from the prompt folder."""

import json
import re

from jsonschema import Draft202012Validator

from reconciliation.core.paths import WORKSPACE

PROMPTS = WORKSPACE / "resources" / "prompts"


def load_schema(name):
    """Read and validate a JSON output schema before any model call."""
    path = PROMPTS / f"{name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8-sig"))
    Draft202012Validator.check_schema(schema)
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError(f"Expected an object output schema: {path}")
    return schema


def load_prompt(name):
    """Read current UTF-8 instructions and reject empty prompt files."""
    path = PROMPTS / f"{name}.md"
    text = path.read_text(encoding="utf-8-sig").rstrip()
    if not text.strip():
        raise ValueError(f"Prompt file is empty: {path}")
    return text


def document_kinds():
    """Return the editable kinds list from its first section heading onward."""
    text = load_prompt("extraction/document_kinds")
    if "\n## " not in "\n" + text:
        raise ValueError("document_kinds.md needs at least one '## Kind' section")
    return text[("\n" + text).index("\n## ") :]


def piece_types():
    """List the kind headings, which are the allowed piece types."""
    return re.findall(r"^## (.+?)\s*$", document_kinds(), re.M)


def extraction_prompt():
    """Join the fixed core rules with the customer-editable document kinds."""
    return load_prompt("extraction/core") + "\n\nDocument kinds:\n" + document_kinds()
