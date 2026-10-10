"""Cache live preview routing only; original bytes are verified on every request."""

import threading

from reconciliation.intake.duplicates import fingerprint


def signature(review):
    """Bind routing to saved metadata contents, never just file timestamps."""
    project = review.manifest_path.parent
    names = (
        'review/index.json',
        'review/state.json',
        'review/receipt-matches.json',
        'review/regeneration.json',
        'bank-output/master_statement.csv',
        'final-review/piece-pipeline.json',
        'final-review/bank-import.json',
        'final-review/decisions.json',
    )
    return tuple((name, fingerprint(project / name) if (project / name).exists() else None) for name in names)


def resolve(review, kind, key):
    """Reuse only source locations; changed metadata rebuilds the workspace-local map."""
    from dashboard.services.matching import piece_matching

    lock = review.__dict__.setdefault('_preview_sources_lock', threading.Lock())
    with lock:
        for _ in range(2):
            before = signature(review)
            cached = getattr(review, '_preview_sources', None)
            if cached is not None and cached[0] == before:
                return cached[1][kind][key]
            _, _, banks, items, _, facts = piece_matching.context(review)
            sources = {
                'bank': {
                    bank_id: (bank['source'], bank.get('source_sha256', facts.get('statement_hash', '')).upper())
                    for bank_id, bank in banks.items()
                },
                'item': {item_id: (item['source_path'], item['document']) for item_id, item in items.items()},
            }
            # Do not publish a lookup assembled across an extraction edit or ledger save.
            if signature(review) == before:
                review._preview_sources = (before, sources)
                return sources[kind][key]
        raise ValueError('Evidence changed while opening the preview. Try again.')
