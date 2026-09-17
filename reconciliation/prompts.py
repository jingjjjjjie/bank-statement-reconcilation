"""Load editable workflow instructions from the workspace prompt folder."""
from reconciliation.paths import WORKSPACE

PROMPTS = WORKSPACE / "prompts"


def load_prompt(name):
    """Read current UTF-8 instructions and reject empty prompt files."""
    path = PROMPTS / f"{name}.md"
    text = path.read_text(encoding="utf-8-sig").rstrip()
    if not text.strip():
        raise ValueError(f"Prompt file is empty: {path}")
    return text
