"""Load editable workflow instructions and schemas from the prompt folder."""
import json
from jsonschema import Draft202012Validator
from reconciliation.paths import WORKSPACE

PROMPTS = WORKSPACE / "prompts"


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
