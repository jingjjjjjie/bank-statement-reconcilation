"""Organize exact duplicates and gate admin cleanup. Python standard library only."""

import argparse
import csv
import errno
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from reconciliation.paths import WORKSPACE

DEFAULT_MANIFEST = WORKSPACE / "duplicate-manifest.json"
CHUNK_SIZE = 1024 * 1024


def fingerprint(path):
    """Read current file bytes for every integrity check."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def identical(left, right):
    with left.open("rb") as a, right.open("rb") as b:
        while True:
            block = a.read(CHUNK_SIZE)
            if block != b.read(CHUNK_SIZE):
                return False
            if not block:
                return True


def supporting_files(root, excluded=()):
    """Scan canonical directories once, rejecting linked entries before collecting files."""
    root = Path(root).resolve()
    excluded = {path.resolve() for path in excluded}
    result = []
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError(f"Linked paths require manual review: {path}")
        for name in files:
            path = Path(directory) / name
            if path not in excluded:
                result.append(path)
    return sorted(result)


def duplicate_groups(files):
    sizes = defaultdict(list)
    for path in files:
        sizes[path.stat().st_size].append(path)
    hashes = defaultdict(list)
    for candidates in sizes.values():
        if len(candidates) > 1:
            for path in candidates:
                hashes[fingerprint(path)].append(path)
    groups = []
    for digest, candidates in sorted(hashes.items()):
        if len(candidates) < 2:
            continue
        # Hashes identify candidates; actual bytes establish identity.
        if not all(identical(candidates[0], path) for path in candidates[1:]):
            raise ValueError("Matching hashes with differing bytes; manual review required.")
        groups.append((digest, sorted(candidates)))
    return groups


def duplicate_root(manifest, manifest_path):
    # Older manifests stored duplicates inside the supporting folder.
    return Path(manifest.get("DuplicateRoot", Path(manifest["SupportingRoot"]) / "duplicated")).resolve()


def review_files(root, manifest, manifest_path):
    # Scan originals and the separate review folder without counting a path twice.
    if manifest.get("Mode") == "exact_report":
        return supporting_files(root)
    destination = duplicate_root(manifest, manifest_path)
    excluded = (manifest_path, destination / "original-locations.csv")
    files = supporting_files(root, excluded)
    if destination.exists() and not destination.is_relative_to(root):
        for group in sorted({record["Group"] for record in manifest["Files"]}):
            if Path(group).name != group or group in (".", ".."):
                raise ValueError("Invalid group name in manifest.")
            folder = destination / group
            if folder.is_dir():
                files += supporting_files(folder, excluded)
    return sorted(set(files))


def move_verified(source, target, expected):
    """Move across mounts only after a durable copy passes hash verification."""
    if target.exists() or fingerprint(source) != expected:
        raise ValueError(f"File changed or target exists: {source}")
    try:
        source.rename(target)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".transfer-", delete=False) as output:
                temporary = Path(output.name)
                with source.open("rb") as input_file:
                    shutil.copyfileobj(input_file, output, CHUNK_SIZE)
                output.flush()
                os.fsync(output.fileno())
            if fingerprint(temporary) != expected or fingerprint(source) != expected:
                raise ValueError(f"File changed during transfer: {source}")
            if target.exists():
                raise ValueError(f"Target appeared during transfer: {target}")
            temporary.rename(target)
            if fingerprint(target) != expected or fingerprint(source) != expected:
                raise ValueError(f"Transfer verification failed: {source}")
            source.unlink()
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    if fingerprint(target) != expected:
        raise ValueError(f"Post-move verification failed: {target}")


def finish_organization(root, manifest, manifest_path):
    """Resume an unfinished manifest without remapping or overwriting documents."""
    root = root.resolve(strict=True)
    destination = duplicate_root(manifest, manifest_path)
    if Path(manifest["SupportingRoot"]).resolve() != root:
        raise ValueError("Manifest belongs to a different supporting root")
    if destination != manifest_path.resolve().parent / "duplicated":
        raise ValueError("Recovery destination must stay beside its manifest")
    # Validate every recorded location before completing any interrupted transfers.
    for record in manifest["Files"]:
        source, target = Path(record["OriginalPath"]), Path(record["OrganizedPath"])
        if not source.resolve().is_relative_to(root) or not target.resolve().is_relative_to(destination):
            raise ValueError("Source or target escaped its expected folder")
        if not source.exists() and not target.exists():
            raise ValueError(f"Both original and review copy are missing: {source}")
        for path in (source, target):
            if path.exists() and fingerprint(path) != record["SHA256"]:
                raise ValueError(f"Recorded document changed: {path}")
    destination.mkdir(exist_ok=True)
    for record in manifest["Files"]:
        source, target = Path(record["OriginalPath"]), Path(record["OrganizedPath"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            if target.exists():
                # A crash after verified publication may leave both identical copies.
                if fingerprint(source) != record["SHA256"] or fingerprint(target) != record["SHA256"]:
                    raise ValueError(f"Recorded document changed: {source}")
                source.unlink()
            else:
                move_verified(source, target, record["SHA256"])
    locations = destination / "original-locations.csv"
    with locations.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["Group", "SHA256", "OriginalPath", "OrganizedPath"])
        writer.writeheader()
        writer.writerows(manifest["Files"])
    manifest["OrganizationComplete"] = True
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def organize(root, manifest_path):
    # Review copies live beside the workspace manifest, outside the source folder.
    destination = manifest_path.resolve().parent / "duplicated"
    if destination.exists() or manifest_path.exists():
        raise ValueError("Existing workflow found. Run check; do not reorganize it.")
    groups = duplicate_groups(supporting_files(root))
    records = []
    for number, (digest, members) in enumerate(groups, 1):
        group = f"group-{number:03d}"
        for copy, source in enumerate(members, 1):
            target = destination / group / f"{copy:02d}__{source.name}"
            if not source.resolve().is_relative_to(root) or not target.resolve().is_relative_to(destination):
                raise ValueError("Source or target escaped its expected folder")
            records.append(dict(Group=group, SHA256=digest,
                                OriginalPath=str(source), OrganizedPath=str(target)))
    manifest = dict(SupportingRoot=str(root), DuplicateRoot=str(destination),
                    Created=datetime.now(timezone.utc).isoformat(), Files=records, OrganizationComplete=False)
    # Write the recovery map before moving any files. Never overwrite a manifest.
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
    finish_organization(root, manifest, manifest_path)
    print(f"Organized {len(records)} files into {len(groups)} groups. No files deleted.")
    return manifest


def check(root, manifest, manifest_path):
    if Path(manifest["SupportingRoot"]).resolve() != root:
        raise ValueError("Manifest belongs to a different supporting root.")
    if manifest.get("Mode") == "exact_report":
        from reconciliation.exact_report import check as check_report
        return check_report(root, manifest)
    destination = duplicate_root(manifest, manifest_path)
    problems = []
    expected = {}
    for record in manifest["Files"]:
        name, digest = record["Group"], record["SHA256"].upper()
        if Path(name).name != name or name in (".", ".."):
            raise ValueError("Invalid group name in manifest.")
        if name in expected and expected[name] != digest:
            raise ValueError("Conflicting fingerprints in manifest.")
        expected[name] = digest
    for name, digest in expected.items():
        folder = destination / name
        if not folder.is_dir():
            problems.append(f"{name}: missing folder")
            continue
        remaining = supporting_files(folder)
        if len(remaining) != 1:
            problems.append(f"{name}: {len(remaining)} files; exactly 1 required")
        elif fingerprint(remaining[0]) != digest:
            problems.append(f"{name}: remaining file does not match original content")
    if destination.exists():
        for folder in destination.iterdir():
            if folder.name == "projects" and destination == manifest_path.resolve().parent / "duplicated":
                continue
            if folder.is_dir() and folder.name not in expected:
                problems.append(f"Unexpected group: {folder.name}")
    remaining = duplicate_groups(review_files(root, manifest, manifest_path))
    if remaining:
        problems.append(f"{len(remaining)} exact duplicate groups still present in supporting tree")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("organize", "check"), nargs="?", default="check")
    parser.add_argument("--root", type=Path, help="Supporting folder; defaults to existing manifest's root")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    try:
        if args.action == "organize":
            if args.root is None:
                raise ValueError("organize requires --root")
            root = args.root.resolve(strict=True)
            if not root.is_dir():
                raise ValueError("Supporting root must be a folder.")
            manifest = organize(root, args.manifest)
        else:
            # utf-8-sig also reads the existing PowerShell-generated manifest.
            manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
            root = (args.root or Path(manifest["SupportingRoot"])).resolve(strict=True)
            if not root.is_dir():
                raise ValueError("Supporting root must be a folder.")
        problems = check(root, manifest, args.manifest)
        if problems:
            print("PENDING: admin cleanup required. Step 2 is blocked.")
            print("\n".join(problems))
            return 2
        print("PASS 1 COMPLETE: every expected group has one unchanged file and no exact duplicates remain. LLM/vision review is still required before the next reconciliation step.")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ERROR: {error}. Step 2 is blocked.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
