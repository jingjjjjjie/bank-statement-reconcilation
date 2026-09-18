"""Record and summarize Codex token usage for the document-review workflow."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")


def record(path, entry):
    """Append one durable audit event before or after a Codex attempt."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {"at": datetime.now(timezone.utc).isoformat(), **entry}
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(event) + "\n")
        log.flush()
        os.fsync(log.fileno())
    if path.name == 'token-usage.jsonl':
        from reconciliation.workspace_usage import persist
        persist(path, event)


def reported_usage(path):
    """Read the last completed turn's reported usage from Codex JSONL output."""
    usage = None
    if not Path(path).exists():
        return None
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            values = event["usage"]
            if all(isinstance(values.get(key), int) and values[key] >= 0 for key in FIELDS):
                usage = {key: values[key] for key in FIELDS}
    return usage


def summary(path):
    """Total reported tokens and expose attempts whose usage is unknown."""
    events = []
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return summarize(events)


def summarize(events):
    """Aggregate audit events without counting cached or reasoning tokens twice."""
    totals = {key: 0 for key in FIELDS}
    attempts = {}
    cache_hits = 0
    for event in events:
        if event.get("status") == "cached":
            cache_hits += 1
        elif event.get("id"):
            attempts[event["id"]] = event
    unknown = 0
    by_stage = {}
    by_model = {}
    for event in attempts.values():
        usage = event.get("usage")
        if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0 for k in FIELDS):
            unknown += 1
            continue
        stage = by_stage.setdefault(event.get("stage", "unknown"), {key: 0 for key in FIELDS})
        model = by_model.setdefault(event.get("model") or "Codex default", {key: 0 for key in FIELDS})
        for key in FIELDS:
            totals[key] += usage[key]
            stage[key] += usage[key]
            model[key] += usage[key]
    return {"totals": totals, "by_stage": by_stage, "by_model": by_model, "attempts": len(attempts),
            "unknown_attempts": unknown, "cache_hits": cache_hits}
