"""One-time move of the existing duplicate review into this workspace."""
import csv
import shutil
import sys
from pathlib import Path

from duplicate_workflow import fingerprint, supporting_files
from vision_workflow import read, save, report


def main():
    # Resolve and check the two explicit folder boundaries before moving anything.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    workspace = Path(__file__).resolve().parent
    manifest_path = workspace / "duplicate-manifest.json"
    manifest = read(manifest_path)
    root = Path(manifest["SupportingRoot"]).resolve(strict=True)
    source = (root / "duplicated").resolve(strict=True)
    target = (workspace / "duplicated").resolve()
    if source.parent != root or target.parent != workspace or target.exists():
        raise ValueError("Unexpected source or occupied destination; nothing moved")
    files = supporting_files(source)
    before = {str(p.relative_to(source)): fingerprint(p) for p in files}

    # Back up metadata and the move plan so any interruption is recoverable.
    backup = workspace / ".tools" / "duplicate-location-backup"
    backup.mkdir(parents=True, exist_ok=False)
    paths = [manifest_path, workspace / "review/index.json", workspace / "review/state.json"]
    for path in paths:
        if path.exists():
            shutil.copy2(path, backup / path.name)
    save(backup / "move-plan.json", {"from": str(source), "to": str(target), "files": before})
    shutil.move(str(source), str(target))
    after = {str(p.relative_to(target)): fingerprint(p) for p in supporting_files(target)}
    if before != after:
        raise ValueError("Moved file verification failed; inspect the saved move plan")

    # Keep historical original paths; change only current organized locations.
    def relocated(value):
        path = Path(value)
        return str(target / path.relative_to(source)) if path.is_relative_to(source) else value

    manifest["DuplicateRoot"] = str(target)
    for record in manifest["Files"]:
        record["OrganizedPath"] = relocated(record["OrganizedPath"])
    save(manifest_path, manifest)
    with (target / "original-locations.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["Group", "SHA256", "OriginalPath", "OrganizedPath"])
        writer.writeheader()
        writer.writerows(manifest["Files"])

    # Preserve prepared units and model state; only their source-path metadata changes.
    index_path, state_path = paths[1:]
    if index_path.exists():
        index, state = read(index_path), read(state_path)
        for document in index["documents"].values():
            document["paths"] = [relocated(p) for p in document["paths"]]
        save(index_path, index)
        state["index_sha256"] = fingerprint(index_path)
        save(state_path, state)
        report(workspace / "review", index, state)
    print(f"Moved {len(before) - 1} supporting files to {target}. All file hashes verified; nothing deleted.")


if __name__ == "__main__":
    main()
