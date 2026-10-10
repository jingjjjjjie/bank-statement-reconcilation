"""Read saved reconciliation projects without activating or processing their inputs."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def list_projects(sources, review=None):
    """Describe managed projects and retain unreadable records as visible warnings."""
    root = sources.workspace / "duplicated/projects"
    manifests = {
        path.resolve() for path in root.glob("*/duplicate-manifest.json")
        if path.resolve().is_relative_to(root.resolve())
    }
    active = review.manifest_path.resolve() if review else None
    if active:
        manifests.add(active)
    projects = []
    for path in manifests:
        item = {
            "id": hashlib.sha256(str(path).encode()).hexdigest()[:24],
            "name": path.parent.name, "workspace": None, "documents": None,
            "active": path == active, "status": "ongoing", "error": "",
            "updated": None,
            "statement": None,
        }
        try:
            manifest = json.loads(path.read_text(encoding="utf-8-sig"))
            source = Path(manifest["SupportingRoot"])
            if not source.is_absolute():
                raise ValueError("Saved project has an invalid source path")
            work = source.parent if source.name == "documents" else source
            item.update(name=work.name, workspace=str(work))
            summary = manifest.get("Summary", {})
            item["documents"] = summary.get("files")
            saved = [path, *(path.parent / "review").glob("*.json")]
            item["updated"] = datetime.fromtimestamp(
                max(file.stat().st_mtime for file in saved), timezone.utc
            ).isoformat()
            if source.name != "documents":
                raise ValueError("Legacy project: select a workspace with documents/ and statement/ folders")
            if not source.is_dir() or not (work / "statement").is_dir():
                raise ValueError("Workspace folder is unavailable")
            statements = [file for file in (work / "statement").iterdir()
                          if file.is_file() and file.suffix.lower() == ".pdf"]
            if len(statements) != 1:
                raise ValueError("statement/ must contain exactly one bank-statement PDF")
            item["statement"] = statements[0].name
            if not manifest.get("OrganizationComplete", False):
                raise ValueError("Workspace setup is incomplete; open it to check the inputs")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            item.update(status="needs_attention", error=str(error))
        projects.append(item)
    return sorted(projects, key=lambda item: (item["updated"] or "", item["name"]), reverse=True)
