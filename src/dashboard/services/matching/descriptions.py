"""Audited manual PARTICULAR text in the existing final-review ledger."""

import re
from datetime import datetime, timezone

from dashboard.services.matching.particulars import confirmed_particular
from dashboard.services.review import write_json
from reconciliation.core.revision import revision

MAX_DESCRIPTION_CHARS = 4000


def bank_binding(bank, facts):
    """Bind manual wording to the bank transaction independently of supporting selections."""
    return revision(
        [
            {
                key: bank.get(key)
                for key in (
                    'id',
                    'transaction_id',
                    'source',
                    'date',
                    'direction',
                    'amount',
                    'currency',
                    'parties',
                    'description',
                )
            },
            bank.get('source_sha256', facts.get('statement_hash', '')),
            bank.get('evidence_revision'),
        ]
    )


def fields(bank, items, state, facts):
    """Expose generated and manually edited text without changing support or approval."""
    saved = state.get('descriptions', {}).get(bank['id'])
    current = bool(saved and not bank.get('bank_source_stale') and saved['bank_revision'] == bank_binding(bank, facts))
    generated = confirmed_particular(bank, items)
    override = saved['text'] if current else None
    return {
        'particular': override if current else generated,
        'generated_particular': generated,
        'particular_override': override,
        'particular_edited': current,
        'particular_stale': bool(saved and not current),
    }


def save(review, body):
    """Save or reset wording with revision checks and history, never approving evidence."""
    from dashboard.services.matching import final_review

    path, state, banks, items, index, facts = final_review.context(review)
    if body.get('binding') != state['binding'] or body.get('version') != state['version']:
        raise ValueError('The report changed. Reload the report before saving this description.')
    bank_id = body.get('bank_id')
    if bank_id not in banks:
        raise ValueError('Choose a valid transaction')
    if 'description' not in body:
        raise ValueError('Provide a description or reset it to the generated text')
    value = body['description']
    if value is not None and (
        not isinstance(value, str)
        or len(value) > MAX_DESCRIPTION_CHARS
        or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', value)
    ):
        raise ValueError('Use plain text up to 4,000 characters for the description')
    bank = banks[bank_id]
    if final_review.source_hash(bank['source']) != bank.get('source_sha256', facts.get('statement_hash', '')).upper():
        raise ValueError('The bank statement changed or is unavailable. Recheck it before editing the description.')
    # Build the response before writing so a display failure cannot conceal a successful save.
    data = final_review.snapshot(review)
    displayed = next(row for row in data['banks'] if row['id'] == bank_id)
    before = state.get('descriptions', {}).get(bank_id)
    at = datetime.now(timezone.utc).isoformat()
    after = (
        None
        if value is None
        else {
            'text': value,
            'bank_revision': bank_binding(bank, facts),
            'at': at,
            'reviewer': 'Local user',
        }
    )
    descriptions = state.setdefault('descriptions', {})
    if after is None:
        descriptions.pop(bank_id, None)
    else:
        descriptions[bank_id] = after
    state['history'].append(
        {
            'bank_id': bank_id,
            'transaction_id': bank['transaction_id'],
            'action': 'reset_description' if value is None else 'edit_description',
            'at': at,
            'reviewer': 'Local user',
            'before': before,
            'after': after,
        }
    )
    state['version'] += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, state)
    return {
        'binding': state['binding'],
        'version': state['version'],
        'bank_id': bank_id,
        'particular': displayed['generated_particular'] if value is None else value,
        'particular_override': value,
        'particular_edited': value is not None,
        'particular_stale': False,
    }
