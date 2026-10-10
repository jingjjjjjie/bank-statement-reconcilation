"""Pure allocation and confidence rules, independent of dashboard sessions."""

from decimal import Decimal

from reconciliation.core.money import amount, normalize_currency


def money(value):
    """Return an explicit monetary value, leaving missing extraction facts unknown."""
    try:
        return amount(value)
    except (ValueError, TypeError):
        return None


def reservations(state, excluding=None):
    """Reserve approved allocations, even if their evidence later becomes stale."""
    used = {}
    for bank_id, decision in state['decisions'].items():
        if bank_id == excluding or decision['status'] != 'approved':
            continue
        for entry in decision['allocations']:
            if entry['amount']:
                used[entry['item_id']] = used.get(entry['item_id'], Decimal(0)) + amount(entry['amount'])
    return used


def pairing_confidence(bank, suggestion, items, decision, stale):
    """Label saved pairing evidence without converting confidence into approval."""
    allocations = suggestion.get('allocations', [])
    if suggestion.get('failed'):
        return {'level': 'failed', 'reason': suggestion.get('reason', 'Matching failed; retry required.')}
    if suggestion.get('outdated'):
        return {
            'level': 'outdated',
            'reason': 'Saved proposal is outdated. Recheck current evidence or generate matches again.',
        }
    if suggestion.get('saved') and not allocations and suggestion.get('assessment') == 'tentative':
        return {'level': 'unresolved', 'reason': suggestion.get('reason', 'Matching remains unresolved.')}
    suggested = {a['item_id']: money(a['amount']) for a in allocations}
    chosen = {a['item_id']: money(a['amount']) for a in decision['allocations']} if decision else {}
    if chosen and chosen != suggested:
        return {
            'level': 'low',
            'reason': 'Supporting selection changed; the saved confidence does not assess this pairing.',
        }
    if not allocations:
        return {'level': None, 'reason': 'No proposed supporting match.'}
    if stale or any(
        a['item_id'] not in items or items[a['item_id']]['stale'] or items[a['item_id']]['excluded']
        for a in allocations
    ):
        return {'level': 'low', 'reason': 'Supporting evidence changed, is unavailable, or is excluded.'}
    values = [money(a['amount']) for a in allocations]
    if any(value is None for value in values) or sum(values, Decimal(0)) != money(bank['amount']):
        return {'level': 'low', 'reason': 'The proposed allocations do not fully explain the bank amount.'}
    if any(items[a['item_id']].get('boundary_unresolved') for a in allocations):
        return {'level': 'low', 'reason': 'Receipt boundaries still need checking against the original document.'}
    level = 'high' if suggestion.get('assessment') == 'strong' else 'low'
    return {
        'level': level,
        'reason': suggestion.get('reason') or 'The saved pairing needs checking against the original evidence.',
    }


def evidence_reason(bank, item):
    """Explain exact extracted facts without inferring identity or approving a match."""

    def names(values):
        """Ignore casing and spacing while preserving meaningful name differences."""
        return {' '.join(value.casefold().split()) for value in values if value.strip()}

    if item.get('stale') or item.get('excluded'):
        return 'Unavailable for confirmation: the source changed or was excluded.'
    parties = names(bank.get('parties', [])), names(item.get('parties', []))
    same_party = bool(parties[0] & parties[1])
    same_amount = (
        bool(item.get('currency'))
        and normalize_currency(item['currency']) == normalize_currency(bank['currency'])
        and money(item.get('amount')) is not None
        and money(item['amount']) == money(bank['amount'])
    )
    if same_party and same_amount:
        return 'Same extracted party name and amount. Check the original and payment context.'
    if same_party:
        return 'Same extracted party name; amount or currency differs or is unknown. Check the allocation.'
    if same_amount:
        return 'Same amount, but no exact extracted party-name match. Amount alone does not establish support.'
    return 'No exact party-and-amount match established. Check references, context and any grouped allocation.'
