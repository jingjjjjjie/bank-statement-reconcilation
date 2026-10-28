"""Read the observed UOB account-activity export without claiming statement completeness."""

import re
from datetime import datetime

from statement_extraction.statement import amount, validate

from .common import MONEY, one

HEADERS = [
    'Statement Date',
    'Transaction Date',
    'Description',
    'Deposit(MYR)',
    'Withdrawal(MYR)',
    'Ledger Balance(MYR)',
]
NOTE = (
    'Filtered account-activity export; full-period completeness is not verified. '
    'Opening balance is inferred. Closing balance is the last listed transaction balance, '
    'not the header account balance.'
)


def counterparty(narration, money_in):
    """Separate repeated bank-code party blocks only when both copies agree."""
    lines = narration.splitlines()
    if len(lines) >= 4 and lines[0] == 'FPX Debit' and lines[-1] == 'GEB':
        return ' '.join(lines[2:-1])
    blocks = re.split(r'\b(?:GEB|PBB|MBB|ABMB|CIMB|HLB)\s+', narration)
    names = [' '.join(block.split('|')[0].split()) for block in blocks[1:]]
    if len(names) == 2:
        # Copies may be cut at different lengths; accept them only when one extends the other.
        short, full = sorted(names, key=len)
        return full if full.startswith(short) else ''
    if len(names) == 1 and len(lines) > 1 and names[0].startswith(lines[1]):
        # Incoming IBG prints the sender's truncated name first and the full name after its bank code.
        return names[0]
    return ''


def read(pdf, path, year):
    """Validate the export's table rows, printed totals, date range, and record count."""
    texts = [page.extract_text() or '' for page in pdf.pages]
    if any(not text.strip() for text in texts):
        raise ValueError('UOB export has a page without readable text.')
    cover = texts[0]
    if 'Account Activities' not in cover or 'CURRENT_ACCOUNT' not in cover:
        raise ValueError('Unsupported UOB export layout or account type.')
    account = one(r'^MYR (\d+)$', cover, 'UOB MYR account')
    start, end = one(r'(\d{2}/\d{2}/\d{4}) - (\d{2}/\d{2}/\d{4})', cover, 'export date range')
    start, end = (datetime.strptime(value, '%d/%m/%Y').date() for value in (start, end))
    if end.year != year or start > end:
        raise ValueError(f'Selected year {year}, but the UOB export ends in {end.year}, or its date range is invalid.')
    count = int(one(r'^(\d+) Record\(s\) \(Note: This is a filtered table\.\)$', cover, 'export record count'))
    header_balance = amount(one(r'Ledger Balance\n[^\n]*MYR ' + MONEY, cover, 'header ledger balance'))
    credit_text, debit_text = one(
        r'Total Deposits\(MYR\) Total Withdrawals\(MYR\)\n' + MONEY + r'\s+' + MONEY, texts[-1], 'export totals'
    )
    rows = []
    for number, (page, text) in enumerate(zip(pdf.pages, texts), 1):
        printed_page, total_pages = one(r'^(\d+) of (\d+)$', text, 'UOB page numbering')
        if int(printed_page) != number or int(total_pages) != len(pdf.pages):
            raise ValueError('Missing, repeated, or reordered UOB pages.')
        if abs(page.width - 595) > 1:
            raise ValueError('Unsupported UOB page width.')
        if number == len(pdf.pages):
            if re.search(r'^\d{2}/\d{2}/\d{4}\s', text, re.M):
                raise ValueError('Unsupported UOB totals page containing transactions.')
            continue
        tables = page.find_tables()
        if len(tables) != 1 or tables[0].extract()[0] != HEADERS:
            raise ValueError(f'Unsupported UOB transaction table on page {number}.')
        table = tables[0]
        if abs(table.bbox[0] - 20) > 1 or abs(table.bbox[2] - 575) > 1:
            raise ValueError('Unsupported UOB table columns.')
        # Body rows span the table width; column borders are printed only in the header.
        boundaries = (20, 100, 187, 310, 383, 473, 575)
        for row in table.rows[1:]:
            _, top, _, bottom = row.bbox
            cells = [
                (page.crop((left, top, right, bottom)).extract_text() or '').strip()
                for left, right in zip(boundaries, boundaries[1:])
            ]
            date_text, transaction_text, narration, incoming, outgoing, balance = cells
            date = datetime.strptime(date_text, '%d/%m/%Y').date()
            timestamp = datetime.strptime(' '.join(transaction_text.split()), '%d/%m/%Y %I:%M:%S %p')
            if not start <= date <= end or timestamp.date() > date or not narration:
                raise ValueError(f'Invalid UOB transaction dates or description on page {number}.')
            rows.append(
                {
                    'date': date.isoformat(),
                    'transaction_datetime': timestamp.isoformat(),
                    'page': number,
                    'narration': narration,
                    'money_in': amount(incoming),
                    'money_out': amount(outgoing),
                    'balance': amount(balance),
                    'balance_origin': 'printed',
                }
            )
    if not rows or len(rows) != count:
        raise ValueError('UOB printed record count mismatch.')
    if any(a['date'] > b['date'] for a, b in zip(rows, rows[1:])):
        raise ValueError('Unexpected UOB statement-date ordering.')
    opening = rows[0]['balance'] - rows[0]['money_in'] + rows[0]['money_out']
    closing = rows[-1]['balance']
    credit, debit = amount(credit_text), amount(debit_text)
    validate(rows, opening, closing, debit, credit)
    return {
        'source': str(path.resolve()),
        'bank': 'uob',
        'account': account,
        'currency': 'MYR',
        'year_supplied': year,
        'statement_kind': 'activity_export',
        'validation_note': NOTE,
        'opening_balance_origin': 'inferred',
        'header_balance': header_balance,
        'opening_balance': opening,
        'closing_balance': closing,
        'total_money_in': credit,
        'total_money_out': debit,
        'balance_checks': 'passed',
        'transactions': rows,
    }
