"""Create a deterministic exact-duplicate report without removing input files."""
import json
import shutil
import tempfile
from pathlib import Path

from reconciliation.duplicate_workflow import duplicate_groups, fingerprint, supporting_files


def copy_verified(source, target, digest):
    """Publish a verified copy without replacing an existing different file."""
    if fingerprint(source) != digest:
        raise ValueError(f"Source changed: {source}")
    if target.exists():
        if fingerprint(target) != digest:
            raise ValueError(f"Output already exists with different content: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".copy-", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        shutil.copyfile(source, temporary)
        if fingerprint(temporary) != digest or fingerprint(source) != digest:
            raise ValueError(f"Source changed while copying: {source}")
        # Exclusive creation prevents overwriting a file created during the copy.
        with target.open("xb") as output, temporary.open("rb") as data:
            shutil.copyfileobj(data, output)
        if fingerprint(target) != digest:
            raise ValueError(f"Copy verification failed: {target}")
    finally:
        temporary.unlink(missing_ok=True)


def save(path, data):
    """Replace the report metadata atomically after verified file operations."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def restore_legacy(root, manifest_path, manifest):
    """Restore previously organized originals by copying, retaining recovery history."""
    actions_path = manifest_path.parent / "dashboard-data/decisions.json"
    actions = json.loads(actions_path.read_text(encoding="utf-8"))["actions"] if actions_path.exists() else []
    for record in manifest["Files"]:
        original = Path(record["OriginalPath"])
        if not original.resolve().is_relative_to(root):
            raise ValueError("Original path escaped the documents folder")
        source = Path(record["OrganizedPath"])
        if not source.is_file():
            candidates = [Path(move["archive"]) for action in actions for move in action["moves"]
                          if move.get("source") == str(source)]
            source = next((path for path in candidates if path.is_file()), source)
        if original.is_file():
            if fingerprint(original) != record["SHA256"]:
                raise ValueError(f"Original changed: {original}")
        else:
            copy_verified(source, original, record["SHA256"])


def prepare(root, manifest_path):
    """Copy every exact group into the work folder's output/duplicates directory."""
    root, manifest_path = root.resolve(), manifest_path.resolve()
    destination = root.parent / "output/duplicates"
    if root.name != "documents" or destination.resolve() != destination.absolute():
        raise ValueError("Duplicate output must be an unlinked output/duplicates folder beside documents")
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    if previous and Path(previous["SupportingRoot"]).resolve() != root:
        raise ValueError("Manifest belongs to another source")
    if previous and previous.get("Mode") != "exact_report":
        restore_legacy(root, manifest_path, previous)
    files = supporting_files(root)
    groups = duplicate_groups(files)
    records = [{"Group": f"group-{number:03d}", "SHA256": digest,
                "OriginalPath": str(source),
                "OrganizedPath": str(destination / f"group-{number:03d}" / f"{copy:02d}__{source.name}")}
               for number, (digest, members) in enumerate(groups, 1)
               for copy, source in enumerate(members, 1)]
    manifest = {"Mode": "exact_report", "SupportingRoot": str(root), "DuplicateRoot": str(destination),
                "Files": records, "SourceHashes": {str(path): fingerprint(path) for path in files},
                "Summary": {"files": len(files), "groups": len(groups), "copies": len(records),
                            "extra_copies": len(records) - len(groups),
                            "unique_documents": len(files) - len(records) + len(groups)},
                "OrganizationComplete": False}
    report_path = destination / "report.json"
    if destination.exists():
        if not report_path.is_file():
            raise ValueError("Duplicate output already exists without a report; existing files were preserved")
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        if saved["Files"] != records or saved["SourceHashes"] != manifest["SourceHashes"]:
            raise ValueError("Sources changed since the duplicate report; preserve the old output before regenerating")
    else:
        destination.mkdir(parents=True)
        save(report_path, manifest)
    for record in records:
        target = Path(record["OrganizedPath"])
        if target.resolve() != target.absolute():
            raise ValueError("Duplicate output contains a linked path")
        copy_verified(Path(record["OriginalPath"]), target, record["SHA256"])
    problems = check(root, manifest)
    if problems:
        raise ValueError("; ".join(problems))
    manifest["OrganizationComplete"] = True
    save(report_path, manifest)
    if previous and previous.get("Mode") != "exact_report":
        backup = manifest_path.with_name("legacy-duplicate-manifest.json")
        if not backup.exists():
            backup.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
    save(manifest_path, manifest)
    return manifest


def check(root, manifest):
    """Verify that reported sources and output copies still match the scanned bytes."""
    current = {str(path): fingerprint(path) for path in supporting_files(root)}
    problems = []
    if current != manifest["SourceHashes"]:
        problems.append("Source files changed since the exact-duplicate report")
    for record in manifest["Files"]:
        target = Path(record["OrganizedPath"])
        if not target.is_file() or target.is_symlink() or fingerprint(target) != record["SHA256"]:
            problems.append(f"Duplicate output missing or changed: {target.name}")
    return problems
