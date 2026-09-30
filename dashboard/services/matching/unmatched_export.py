"""Build a deduplicated unmatched-document archive without changing source files."""

import hashlib
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from dashboard.services.matching import final_review
from reconciliation.extraction.workflow import inventory, load_index, removal_plan
from reconciliation.intake.duplicates import CHUNK_SIZE, identical


def matched_documents(review):
    """Exclude whole documents with any current human-approved match, including partial links."""
    if not (review.manifest_path.parent / 'final-review/decisions.json').exists():
        return set()
    data = final_review.snapshot(review)
    return {
        entry['document']
        for bank in data['banks']
        if bank['review_status'] == 'approved' and not bank['stale']
        for entry in bank['decision']['allocations']
    }


def archive_files(review):
    """Choose one unchanged source per hash, restoring legacy copies to original relative paths."""
    root = review.root.resolve(strict=True)
    manifest = final_review.read(review.manifest_path)
    if Path(manifest['SupportingRoot']).resolve() != root:
        raise ValueError('Document manifest belongs to another workspace')
    current = inventory(root, review.manifest_path)
    removed = {}
    work = review.manifest_path.parent / 'review'
    if (work / 'index.json').exists():
        index, state = load_index(work)
        if Path(index['manifest']).resolve() != review.manifest_path.resolve():
            raise ValueError('Prepared review belongs to another workspace')
        removed = removal_plan(state)
    excluded = matched_documents(review) | {loser for loser, keeper in removed.items() if keeper in current}
    originals = {str(Path(row['OrganizedPath']).resolve()): Path(row['OriginalPath']) for row in manifest['Files']}
    selected, names = [], set()
    for digest, locations in sorted(current.items()):
        if digest in excluded:
            continue
        paths = [Path(path) for path in locations]
        if any(not identical(paths[0], path) for path in paths[1:]):
            raise ValueError('Files with matching hashes have different bytes')
        candidates = []
        for path in paths:
            original = originals.get(str(path.resolve()), path).resolve()
            if not original.is_relative_to(root):
                raise ValueError('Document location is outside the uploads folder')
            relative = original.relative_to(root)
            if any('\\' in part or ':' in part for part in relative.parts):
                raise ValueError('Document filename cannot be safely stored in a portable ZIP')
            candidates.append((relative.as_posix(), path))
        relative, path = min(candidates, key=lambda pair: pair[0])
        name = 'uploads/' + relative
        if name.casefold() in names:
            raise ValueError('Document paths conflict in the ZIP; originals were preserved')
        names.add(name.casefold())
        selected.append((path, name, digest))
    return selected


def export_zip(review):
    """Write a temporary ZIP, verifying every included file as it is copied."""
    files = archive_files(review)
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temporary:
        path = Path(temporary.name)
    try:
        with ZipFile(path, 'w', compression=ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr('uploads/', b'')
            for source, name, expected in files:
                digest = hashlib.sha256()
                with source.open('rb') as input_file, archive.open(name, 'w', force_zip64=True) as output:
                    for block in iter(lambda: input_file.read(CHUNK_SIZE), b''):
                        digest.update(block)
                        output.write(block)
                if digest.hexdigest().upper() != expected:
                    raise ValueError('A document changed during export; retry the download')
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise
