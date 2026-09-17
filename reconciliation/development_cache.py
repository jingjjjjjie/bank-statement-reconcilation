"""Optional workspace-wide testing cache with immutable output snapshots."""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from reconciliation.paths import WORKSPACE


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
    """Default to normal operation unless development mode is explicitly enabled."""
    path = WORKSPACE / "config/development.local.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"enabled": False}


def set_mode(enabled):
    """Persist the development switch without deleting cache data."""
    if type(enabled) is not bool:
        raise ValueError("Development mode must be true or false")
    write_json(WORKSPACE / "config/development.local.json", {"enabled": enabled})
    return mode()


def root_for(path):
    """Enable the shared cache only for this workspace's development runs."""
    if Path(path).resolve().is_relative_to(WORKSPACE.resolve()) and mode()["enabled"]:
        return WORKSPACE / "duplicated/development-cache"
    return None


def project_key(source):
    """Scope human decisions to the source folder, independently of review resets."""
    return hashlib.sha256(str(Path(source).resolve()).encode()).hexdigest()[:24]


def project_folder(manifest):
    """Locate shared project history while preserving original source locations."""
    root = root_for(manifest)
    if root is None:
        return None
    source = json.loads(Path(manifest).read_text(encoding="utf-8-sig"))["SupportingRoot"]
    return root / "projects" / project_key(source)


def copy_atomic(source, target):
    """Copy an artifact without exposing partially written cache files."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}-{uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def share_request(work, folder):
    """Keep request prompts, schemas, responses, and failed-attempt logs centrally."""
    root = root_for(work)
    if root is not None:
        for path in folder.iterdir():
            if path.is_file() and not path.name.startswith(".") and path.suffix != ".tmp":
                copy_atomic(path, root / "model-requests" / folder.name / path.name)


def capture(manifest, stage, extra=()):
    """Snapshot generated outputs by content hash; never automatically restore state."""
    manifest = Path(manifest).resolve()
    project = project_folder(manifest)
    if project is None:
        return None
    root = project.parent.parent
    base = manifest.parent
    paths = [manifest, base / "review_config.json"]
    for directory in ("review", "bank-output", "dashboard-data"):
        parent = base / directory
        if parent.exists():
            paths.extend(p for p in parent.rglob("*") if p.is_file()
                         and not {"model-cache", "history", "recovery"}.intersection(p.relative_to(parent).parts)
                         and p.suffix != ".tmp" and not p.name.startswith("."))
    paths.extend(Path(p) for p in extra)
    artifacts = {}
    for path in paths:
        if not path.is_file():
            continue
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        blob = root / "objects" / digest[:2] / digest
        if not blob.exists():
            blob.parent.mkdir(parents=True, exist_ok=True)
            temporary = blob.with_name(f".{uuid4().hex}.tmp")
            temporary.write_bytes(payload)
            temporary.replace(blob)
        label = path.relative_to(base).as_posix() if path.is_relative_to(base) else "exports/" + path.name
        artifacts[label] = {"sha256": digest, "bytes": len(payload), "source": str(path)}
    data = {"version": 1, "manifest": str(manifest), "stage": stage, "artifacts": artifacts}
    key = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    snapshot = project / "snapshots" / f"{key}.json"
    if not snapshot.exists():
        write_json(snapshot, {**data, "at": datetime.now(timezone.utc).isoformat()})
    write_json(project / "latest-output.json", {"snapshot": snapshot.name, "stage": stage})
    return snapshot
