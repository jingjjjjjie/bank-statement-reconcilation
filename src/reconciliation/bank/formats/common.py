"""Shared strict column reading and validation for bank-specific layouts."""

import re
from datetime import datetime
from decimal import Decimal

from reconciliation.bank.statement import amount, cell, validate

MONEY = r"([\d,]+\.\d{2})"


def one(pattern, text, label):
    """Require one unambiguous source field."""
    matches = re.findall(pattern, text, re.M)
    if len(matches) != 1:
        raise ValueError(f'Missing or ambiguous {label}; this statement layout is unsupported.')
    return matches[0]


def read_layout(pdf, path, year, bank):
    """Read fixed verified columns and reconcile every available source control."""
    texts = [page.extract_text() or '' for page in pdf.pages]
    if any(not text.strip() for text in texts):
        raise ValueError('Statement has a page without readable text; scanned statements are not supported.')
    cover, whole = texts[0], '\n'.join(texts)
    from . import BANKS, layout

    reader = layout(bank)
    spec = reader.specification(cover, whole, texts)
    account_pattern, period, opening, closing = (
        spec['account_pattern'],
        spec['period'],
        spec['opening'],
        spec['closing'],
    )
    debit, credit, counts = spec['debit'], spec['credit'], spec['counts']
    header, width, columns = spec['header'], spec['width'], spec['columns']
    date_format, page_pattern = spec['date_format'], spec['page_pattern']
    if period.year != year:
        raise ValueError(f'Selected year {year}, but the statement date is in {period.year}.')
    account = one(account_pattern, cover, 'account number')
    rows, current_date, ended = [], None, False
    for page_number, (page, text) in enumerate(zip(pdf.pages, texts), 1):
        numbers = one(page_pattern, text, 'page numbering')
        numbers = (numbers,) if isinstance(numbers, str) else numbers
        if int(numbers[0]) != page_number or (len(numbers) == 2 and int(numbers[1]) != len(pdf.pages)):
            raise ValueError('Missing, repeated, or reordered statement pages.')
        accounts = re.findall(account_pattern, text)
        if (accounts or spec.get('account_each_page', True)) and accounts != [account]:
            raise ValueError('Multiple accounts or conflicting account headers are unsupported.')
        if abs(page.width - width) > 1:
            raise ValueError(f'Unsupported {BANKS[bank]} page size on page {page_number}.')
        lines = page.extract_text_lines()
        headers = [i for i, line in enumerate(lines) if line['text'] == header]
        if len(headers) != 1:
            raise ValueError(f'Unsupported {BANKS[bank]} table header on page {page_number}.')
        for line in lines[headers[0] + 1 :]:
            if spec.get('ignore_rotated') and not any(c.get('upright', True) for c in line['chars']):
                continue
            text = line['text']
            # Printed notices are outside the transaction region.
            if ended:
                if re.match(r'^\d{2}[/-]\d{2}(?:[/-]\d{4})?\s', text):
                    raise ValueError('Unexpected transactions after statement totals.')
                continue
            if text.startswith(spec['skip_prefixes']):
                continue
            if text.startswith(spec['end_prefix']):
                ended = True
                continue
            if text.startswith(spec['page_end']):
                break
            left = columns[0]
            date_text = cell(line, 0, left)
            narration = cell(line, left, columns[1])
            if spec.get('signed'):
                signed, balance_text = cell(line, columns[1], columns[2]), cell(line, columns[2], page.width)
                incoming = signed[:-1] if signed.endswith('+') else ''
                outgoing = signed[:-1] if signed.endswith('-') else ''
                if signed and not (incoming or outgoing):
                    raise ValueError(f'Invalid signed amount on page {page_number}.')
            else:
                first, second = cell(line, columns[1], columns[2]), cell(line, columns[2], columns[3])
                incoming, outgoing = (first, second) if spec.get('deposits_first') else (second, first)
                balance_text = cell(line, columns[3], page.width)
            if hasattr(reader, 'transaction_cells'):
                date_text, narration, incoming, outgoing, balance_text = reader.transaction_cells(line, page)
            if narration.startswith(spec['opening_prefix']):
                continue
            if narration.startswith(('Balance B/F', 'Balance C/F')):
                if not rows or amount(balance_text) != rows[-1]['balance']:
                    raise ValueError(f'Carry-forward balance mismatch on page {page_number}.')
                continue
            if incoming or outgoing:
                if bool(incoming) == bool(outgoing):
                    raise ValueError(f'Ambiguous debit/credit on page {page_number}.')
                if date_text:
                    if spec.get('entry_date_right'):
                        # Use entry date for reconciliation, not the adjacent value date.
                        date_text = cell(line, 0, spec['entry_date_right'])
                    if spec.get('monthly_dates'):
                        parsed = datetime.strptime(f'{date_text}/{year}', '%d/%m/%Y')
                        if parsed.month != period.month:
                            raise ValueError('Transaction date is outside the statement month.')
                    else:
                        parsed = datetime.strptime(date_text, date_format)
                    current_date = parsed.date()
                elif not spec.get('carry_dates'):
                    raise ValueError(f'Missing transaction date on page {page_number}.')
                if current_date is None or current_date > period.date():
                    raise ValueError(f'Invalid transaction date on page {page_number}.')
                if spec.get('start_date') and current_date < spec['start_date']:
                    raise ValueError(f'Transaction date is outside the statement period on page {page_number}.')
                if not balance_text and not spec.get('sparse_balances'):
                    raise ValueError(f'Missing printed balance on page {page_number}.')
                rows.append(
                    {
                        'date': current_date.isoformat(),
                        'page': page_number,
                        'narration': narration,
                        'money_in': amount(incoming) if incoming else Decimal('0.00'),
                        'money_out': amount(outgoing) if outgoing else Decimal('0.00'),
                        'direction': 'in' if incoming else 'out',
                        'balance': amount(balance_text) if balance_text else None,
                        'balance_origin': 'printed' if balance_text else 'calculated',
                    }
                )
            elif narration and rows and not date_text and not balance_text:
                rows[-1]['narration'] += '\n' + narration
            elif text.strip():
                raise ValueError(f'Unrecognized transaction line on page {page_number}: {text}')
    if not ended:
        raise ValueError('Missing statement end/totals.')
    if spec.get('reverse'):
        rows.reverse()
    if any(a['date'] > b['date'] for a, b in zip(rows, rows[1:])):
        raise ValueError('Unexpected transaction date ordering.')
    balance = opening
    for row in rows:
        balance += row['money_in'] - row['money_out']
        if row['balance'] is None:
            row['balance'] = balance
    if counts and counts != (sum(r['direction'] == 'out' for r in rows), sum(r['direction'] == 'in' for r in rows)):
        raise ValueError('Printed transaction count mismatch.')
    validate(rows, opening, closing, debit, credit, allow_zero=spec.get('allow_zero', False))
    return {
        'source': str(path.resolve()),
        'bank': bank,
        'account': account,
        'currency': 'MYR',
        'year_supplied': year,
        'opening_balance': opening,
        'closing_balance': closing,
        'total_money_in': credit,
        'total_money_out': debit,
        'balance_checks': 'passed',
        'transactions': rows,
    }
