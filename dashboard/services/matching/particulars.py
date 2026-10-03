"""Format confirmed supporting evidence for statement particulars."""

from decimal import Decimal, InvalidOperation


def particular(item):
    """Join only known receipt number, payee, description and source amount."""
    number = item.get('document_number') or ' / '.join(item.get('invoice_numbers') or [])
    fields = [f'RECEIPT NO {number}' if number else '', item.get('payee'), item.get('description')]
    value = item.get('amount')
    if value not in (None, ''):
        try:
            amount = Decimal(str(value))
            if amount.is_finite():
                fields.append(format(amount, ',.2f'))
        except InvalidOperation:
            pass
    return ' : '.join(str(value).strip() for value in fields if value and str(value).strip())


def confirmed_particular(bank, items):
    """Keep pending, rejected and stale evidence out of exported particulars."""
    if bank['review_status'] != 'approved' or bank['stale']:
        return ''
    return '\n'.join(
        text for allocation in (bank['decision'] or {}).get('allocations', [])
        if (text := particular(items[allocation['item_id']]))
    )
