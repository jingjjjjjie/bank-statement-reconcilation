"""Export original inputs and confirmed supporting documents without changing them."""

import os
from pathlib import Path

from dashboard.services.matching import final_review, unmatched_export
from reconciliation.extraction.workflow import inventory
from reconciliation.intake.duplicates import fingerprint

GENERATED = {'output', 'review', 'duplicated', 'bank-output', 'final-review', 'dashboard-data'}


def portable_name(path):
    """Reject ambiguous archive names instead of silently renaming source files."""
    if any(part in ('..', '.') or '\\' in part or ':' in part for part in path.parts):
        raise ValueError('Source filename cannot be safely stored in a portable ZIP')
    return path.as_posix()


def original_documents(review, matched=False):
    """Keep every original copy and restore legacy organized paths inside the ZIP."""
    root = review.root.resolve(strict=True)
    manifest = final_review.read(review.manifest_path)
    if Path(manifest['SupportingRoot']).resolve() != root:
        raise ValueError('Document manifest belongs to another workspace')
    originals = {str(Path(row['OrganizedPath']).resolve()): Path(row['OriginalPath']) for row in manifest['Files']}
    selected = unmatched_export.matched_documents(review) if matched else None
    files = {}
    for digest, locations in inventory(root, review.manifest_path).items():
        if selected is not None and digest not in selected:
            continue
        for location in locations:
            source = Path(location)
            original = originals.get(str(source.resolve()), source).resolve()
            if not original.is_relative_to(root):
                raise ValueError('Original document is outside the supporting folder')
            expected = manifest.get('SourceHashes', {}).get(str(original), digest)
            if digest != expected:
                raise ValueError('Original document changed since intake; cannot export its initial state')
            name = portable_name(Path(root.name) / original.relative_to(root))
            files[name] = (source, name, digest)
    if not matched:
        for original in manifest.get('SourceHashes', {}):
            name = portable_name(Path(root.name) / Path(original).relative_to(root))
            if name not in files:
                raise ValueError('An original document is missing; cannot export its initial state')
    return list(files.values())


def source_directories(root, prefix, excluded=()):
    """Scan original folders without following links or generated root directories."""
    def fail(error):
        """Never present an unreadable folder as a complete export."""
        raise error

    files, directories = [], [prefix.as_posix() + '/']
    for directory, folders, names in os.walk(root, followlinks=False, onerror=fail):
        current = Path(directory)
        if current == root:
            folders[:] = [name for name in folders if name.casefold() not in excluded]
        for name in folders + names:
            path = current / name
            if path.is_symlink() or path.is_junction():
                raise ValueError('Linked paths cannot be included in an original export')
        directories.extend(portable_name(prefix / (current / name).relative_to(root)) + '/' for name in folders)
        for name in names:
            path = current / name
            files.append((path, portable_name(prefix / path.relative_to(root)), fingerprint(path)))
    return files, directories


def export_zip(review, kind):
    """Build original documents, original project or approved-match archives."""
    if kind not in {'original', 'project', 'matched'}:
        raise ValueError('Unknown document export option')
    root = review.root.resolve(strict=True)
    files = original_documents(review, matched=kind == 'matched')
    directories = [root.name + '/']
    if kind == 'original':
        _, directories = source_directories(root, Path(root.name))
    elif kind == 'project':
        workspace = root.parent
        if root.name != 'documents' or not (workspace / 'statement').is_dir():
            raise ValueError('Original project export requires a workspace with documents and statement folders')
        extras, directories = source_directories(workspace, Path(workspace.name), GENERATED)
        prefix = workspace.name + '/'
        files = [(path, prefix + name, digest) for path, name, digest in files]
        files.extend(entry for entry in extras if not entry[1].startswith(prefix + root.name + '/'))
    names = [name.casefold() for _, name, _ in files]
    if len(names) != len(set(names)):
        raise ValueError('Original paths conflict in the ZIP')
    return unmatched_export.write_zip(files, directories)
