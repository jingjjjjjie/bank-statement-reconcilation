"""Development mode: remember exact-duplicate keep choices and replay them in later test runs."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dashboard import content_review
from reconciliation import development_cache


def path(review):
    """Prefer a pinned shared preset, then the latest automatically saved choices."""
    project = development_cache.project_folder(review.manifest_path)
    if project is None:
        return review.data / "development-decisions.json"
    preset = project / "decisions/preset.json"
    return preset if preset.exists() else project / "decisions/latest.json"


def snapshot(review):
    """Report reusable decisions and cached outputs without applying anything."""
    target = path(review)
    result = {"saved": False, "exact": 0}
    if target.is_file():
        data = json.loads(target.read_text(encoding="utf-8"))
        result.update(saved=bool(data["exact"]), at=data["at"], exact=len(data["exact"]))
    root = development_cache.root_for(review.manifest_path)
    if root is not None:
        result["cache"] = {"path": str(root), "model_results": len(list((root / "model-requests").glob("*/result.json")))}
    return result


def capture(review, pin=False):
    """Automatically preserve decisions; pinning keeps a preset through later undos."""
    project = development_cache.project_folder(review.manifest_path)
    if project is None and not pin:
        return None
    exact = []
    for group in review.snapshot()["groups"]:
        if group["status"] == "reviewed" and group["kept"]:
            record = review.records[group["kept"]]
            exact.append({"hash": record["SHA256"], "original": record["OriginalPath"],
                          "relative": Path(record["OriginalPath"]).relative_to(review.root).as_posix()})
    data = {"at": datetime.now(timezone.utc).isoformat(), "exact": exact}
    data.update(version=1, source=str(review.root), manifest=str(review.manifest_path))
    if project is None:
        development_cache.write_json(path(review), data)
    else:
        folder = project / "decisions"
        development_cache.write_json(folder / "history" / f"{uuid4().hex}.json", data)
        development_cache.write_json(folder / "latest.json", data)
        if pin:
            development_cache.write_json(folder / "preset.json", data)
        development_cache.capture(review.manifest_path, "human-decisions")
    return snapshot(review)


def remember(review):
    """Pin the current human choices for explicit replay during later tests."""
    return capture(review, pin=True)


def seed(review):
    """Preserve existing outputs and choices when development mode is enabled."""
    project = development_cache.project_folder(review.manifest_path)
    if project is None:
        return
    for parent in review.manifest_path.parent.rglob("model-cache"):
        for folder in parent.iterdir():
            if folder.is_dir():
                development_cache.share_request(parent.parent, folder)
    legacy = review.data / "development-decisions.json"
    preset = project / "decisions/preset.json"
    if legacy.is_file() and not preset.exists():
        development_cache.copy_atomic(legacy, preset)
    capture(review)


def apply(review, reviewer):
    """Replay matching human choices only after an explicit named action."""
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("Enter your name before applying remembered decisions")
    if content_review.execution_status(review)["running"]:
        raise ValueError("Wait for the current content-review batch to finish")
    target = path(review)
    if not target.is_file():
        raise ValueError("Remember decisions first")
    data = json.loads(target.read_text(encoding="utf-8"))
    exact_count = 0
    groups = {item["id"]: item for item in review.snapshot()["groups"]}
    identities = {(record["SHA256"], record["OriginalPath"]): (group, file_id)
                  for group, ids in review.groups.items() for file_id in ids
                  for record in [review.records[file_id]]}
    for saved in data["exact"]:
        match = identities.get((saved["hash"], saved["original"]))
        if match is None:
            continue
        group, file_id = match
        if groups[group]["status"] == "pending":
            review.keep(group, file_id)
            groups[group]["status"] = "reviewed"
            exact_count += 1
    return {"exact_applied": exact_count, "saved": snapshot(review)}
