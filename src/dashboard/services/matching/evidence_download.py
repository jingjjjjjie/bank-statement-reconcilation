"""Download only the current approved originals for one bank transaction."""

from pathlib import Path

from dashboard.services.matching import final_review
from dashboard.services.source_export import portable_name


def approved_files(review, bank_id):
    """Resolve unique approved documents from a fresh ledger and verified evidence."""
    data = final_review.snapshot(review)
    bank = next((row for row in data['banks'] if row['id'] == bank_id), None)
    if bank is None:
        raise KeyError(bank_id)
    if bank['review_status'] != 'approved' or bank['stale']:
        raise ValueError('This transaction needs a current approval before downloading evidence')
    items = {item['id']: item for item in data['items']}
    files, seen, names = [], set(), set()
    root = review.root.resolve()
    for allocation in bank['decision']['allocations']:
        item = items[allocation['item_id']]
        digest = item['document']
        if digest in seen:
            continue
        source = Path(item['source_path'])
        resolved = source.resolve()
        relative = resolved.relative_to(root) if resolved.is_relative_to(root) else Path(source.name)
        name = portable_name(relative)
        if name.casefold() in names:
            name = portable_name(Path(digest) / source.name)
        if name.casefold() in names:
            raise ValueError('Evidence filenames conflict in the ZIP')
        names.add(name.casefold())
        seen.add(digest)
        files.append((source, name, digest))
    if not files:
        raise ValueError('No approved supporting documents for this transaction')
    return files
