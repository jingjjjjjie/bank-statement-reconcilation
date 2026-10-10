"""Retired development-mode guard and atomic JSON publication."""

import json
from uuid import uuid4


def write_json(path, value):
    """Publish JSON atomically without sharing temporary names between workers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def mode():
    """Keep retired development features disabled, including old saved flags."""
    return {"enabled": False}
