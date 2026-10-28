"""Extract supported single-account digital bank statements locally."""

import argparse
import csv
import hashlib
import re
from decimal import Decimal
from pathlib import Path

import pdfplumber
from pdfminer.pdftypes import resolve1
from pdfplumber.utils.exceptions import PdfminerException

# Keep money exact and retain the evidence needed for later matching.
MONEY = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}")
DEFAULT_METADATA = {
    'bank': 'ambank',
    'statement_kind': 'statement',
    'validation_note': '',
    'opening_balance_origin': 'printed',
    'header_balance': '',
}
MASTER_FIELDS = [
    "transaction_id",
    "source",
    "source_sha256",
    "bank",
    'statement_kind',
    'validation_note',
    'opening_balance_origin',
    'header_balance',
    "page",
    "sequence",
    "account",
    "currency",
    "year_supplied",
    "date",
    'transaction_datetime',
    "direction",
    "money_in",
    "money_out",
    "balance",
    "balance_origin",
    "transaction_type",
    "counterparty",
    "counterparty_role",
    "counterparty_raw",
    "details_raw",
    "particular",
    "narration",
    "opening_balance",
    "closing_balance",
    "total_money_in",
    "total_money_out",
    "balance_checks",
    "matching_status",
]


def plausible_party(party):
    """Reject reference-like text so a misread field becomes REVIEW PAY TO, never a payee."""
    letters = sum(c.isalpha() for c in party)
    digits = sum(c.isdigit() for c in party)
    return letters >= 2 and digits <= letters / 3 and not re.search(r'\d{5,}|\.TXT\b', party, re.I)


def describe(narration, money_in, bank='ambank', direction=None):
    """Apply bank-specific party rules while keeping original evidence."""
    from statement_extraction.formats import layout

    if bank != 'ambank':
        # Only known party fields are separated; all source narration remains intact.
        party = layout(bank).counterparty(narration, money_in)
        party = party if plausible_party(party) else ''
        lines = narration.splitlines()
        return {
            'transaction_type': lines[0] if lines else '',
            'counterparty': party,
            'counterparty_role': 'payer' if money_in or direction == 'in' else 'recipient',
            'counterparty_raw': party,
            'details_raw': narration,
            'particular': '',
        }
    fields = layout(bank).describe(narration, money_in)
    if not plausible_party(fields['counterparty']):
        fields['counterparty'] = ''
    return fields


def payees(rows, bank):
    """Describe every row, then fill blanks from the statement's own clean names and linked transfers."""
    fields = [describe(r['narration'], r['money_in'], bank, r.get('direction')) for r in rows]
    known = sorted({f['counterparty'] for f in fields if len(f['counterparty']) >= 6}, key=len, reverse=True)
    transfers = {}
    for row, field in zip(rows, fields):
        for reference in re.findall(r'\b\d{9,}\b', row['narration'].splitlines()[0]):
            if field['counterparty']:
                transfers.setdefault(reference, set()).add(field['counterparty'])
    for row, field in zip(rows, fields):
        lines = row['narration'].splitlines()
        if field['counterparty'] or len(lines) < 2 and not re.search(r'FEE|CHARGE', lines[0]):
            continue
        if re.search(r'\bFEE\b|CHARGE', lines[0]):
            # A fee takes its transfer's payee by reference; a reference shared by different payees stays REVIEW.
            names = {name for r in re.findall(r'\b\d{9,}\b', lines[0]) for name in transfers.get(r, ())}
            party = names.pop() if len(names) == 1 else ''
        else:
            # A purpose may sit before or after a payee already printed cleanly elsewhere in the statement.
            party = next((n for n in known if re.search(rf'(^{re.escape(n)}\s|\s{re.escape(n)}$)', lines[1])), '')
        if party:
            field['counterparty'] = field['counterparty_raw'] = party
    return fields


def write_master(result, path):
    """Write a self-contained CSV master, including statement-level checks."""
    metadata = {**DEFAULT_METADATA, **{k: v for k, v in result.items() if k != "transactions"}}
    metadata["source_sha256"] = hashlib.sha256(Path(result["source"]).read_bytes()).hexdigest()
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=MASTER_FIELDS)
        writer.writeheader()
        parties = payees(result["transactions"], metadata['bank'])
        for sequence, (row, party) in enumerate(zip(result["transactions"], parties), 1):
            writer.writerow(
                {
                    **metadata,
                    **row,
                    'transaction_datetime': row.get('transaction_datetime', ''),
                    'balance_origin': row.get('balance_origin', 'printed'),
                    **party,
                    "sequence": sequence,
                    "transaction_id": f"{metadata['source_sha256']}:{sequence:04d}",
                    "direction": row.get('direction', "in" if row["money_in"] else "out"),
                    "matching_status": "pending",
                }
            )


def read_master(path):
    """Validate the master before producing an answer workbook."""
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ValueError("Master CSV contains no transactions")
    for row in rows:
        for key, default in DEFAULT_METADATA.items():
            row[key] = row.get(key) or default
        row['transaction_datetime'] = row.get('transaction_datetime') or ''
        row['balance_origin'] = row.get('balance_origin') or 'printed'
    summary_keys = (
        "source",
        "source_sha256",
        "bank",
        'statement_kind',
        'validation_note',
        'opening_balance_origin',
        'header_balance',
        "account",
        "currency",
        "year_supplied",
        "opening_balance",
        "closing_balance",
        "total_money_in",
        "total_money_out",
    )
    for row in rows:
        if any(row[k] != rows[0][k] for k in summary_keys):
            raise ValueError("Inconsistent statement metadata in master CSV")
        for key in ("money_in", "money_out", "balance"):
            row[key] = amount(row[key])
    result = {key: rows[0][key] for key in summary_keys}
    validate(
        rows,
        *(amount(result[k]) for k in ("opening_balance", "closing_balance", "total_money_out", "total_money_in")),
        allow_zero=result['bank'] == 'public_bank',
    )

    # Bind each CSV row to the unchanged PDF, not merely to plausible arithmetic.
    source = Path(result["source"])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != result["source_sha256"]:
        raise ValueError("Source PDF fingerprint changed")
    original = extract(source, int(result["year_supplied"]), result['bank'])
    for key, default in DEFAULT_METADATA.items():
        if str(result[key]) != str(original.get(key, default)):
            raise ValueError(f'Master {key} differs from source PDF')
    for key in ("account", "currency"):
        if result[key] != original[key]:
            raise ValueError(f"Master {key} differs from source PDF")
    if len(rows) != len(original["transactions"]):
        raise ValueError("Master row count differs from source PDF")
    parties = payees(original["transactions"], result['bank'])
    for number, (row, expected, derived) in enumerate(zip(rows, original["transactions"], parties), 1):
        # Older payee rules only ever copied text from the row itself; anything else is an edit.
        saved = ' '.join(row.get('counterparty', '').split()).upper()
        if saved and saved != derived['counterparty'].upper() and saved not in ' '.join(expected['narration'].split()).upper():
            raise ValueError(f"Master row {number} differs from source extraction")
        row.update(derived)
        required = {
            **expected,
            'transaction_datetime': expected.get('transaction_datetime', ''),
            "sequence": number,
            "transaction_id": f"{digest}:{number:04d}",
            "direction": expected.get('direction', "in" if expected["money_in"] else "out"),
            'balance_origin': expected.get('balance_origin', 'printed'),
        }
        if any(str(row[key]) != str(value) for key, value in required.items()):
            raise ValueError(f"Master row {number} differs from source extraction")
    for key in ("opening_balance", "closing_balance", "total_money_in", "total_money_out"):
        if amount(result[key]) != original[key]:
            raise ValueError(f"Master {key} differs from source PDF")
    return {**result, "transactions": rows}


def amount(text):
    """Reject ambiguous numeric cells instead of guessing."""
    if not MONEY.fullmatch(text):
        raise ValueError(f"Invalid money cell: {text!r}")
    return Decimal(text.replace(",", ""))


def cell(line, left, right):
    """Read a text column using verified page coordinates."""
    chars = [c for c in line["chars"] if left <= c["x0"] < right]
    return pdfplumber.utils.extract_text(chars, x_tolerance=1).strip() if chars else ""


def validate(rows, opening, closing, debit_total, credit_total, allow_zero=False):
    """Check each balance and both independent printed monthly totals."""
    if not rows or any(v is None for v in (opening, closing, debit_total, credit_total)):
        raise ValueError("Missing transactions, opening/closing balance, or printed totals")
    balance = opening
    for number, row in enumerate(rows, 1):
        zero = allow_zero and row.get('direction') in ('in', 'out') and row['money_in'] == row['money_out'] == 0
        if min(row["money_in"], row["money_out"]) < 0 or (bool(row["money_in"]) == bool(row["money_out"]) and not zero):
            raise ValueError(f"Expected one positive debit or credit at transaction {number}")
        balance += row["money_in"] - row["money_out"]
        if balance != row["balance"]:
            raise ValueError(f"Balance mismatch at transaction {number}, page {row['page']}")
    if balance != closing:
        raise ValueError("Closing balance mismatch")
    if sum(r["money_out"] for r in rows) != debit_total:
        raise ValueError("Printed debit total mismatch")
    if sum(r["money_in"] for r in rows) != credit_total:
        raise ValueError("Printed credit total mismatch")


def read_bank(pdf, path, year, bank):
    """Dispatch one open PDF to a single bank's verified layout reader."""
    from statement_extraction.formats import layout
    from statement_extraction.formats.common import read_layout

    reader = layout(bank)
    if hasattr(reader, 'read'):
        return reader.read(pdf, path, year)
    if bank != 'ambank':
        return read_layout(pdf, path, year, bank)
    from statement_extraction.formats.ambank import extract as extract_ambank

    return extract_ambank(path, year)


def extract(path, year, bank='ambank'):
    """Try each issuer named on page 1; accept only when exactly one layout passes every check."""
    from statement_extraction.formats import BANKS, check_selection, names

    path = Path(path)
    if type(year) is not int or not 1900 <= year <= 2100:
        raise ValueError('Enter a valid statement year (1900-2100).')
    try:
        document = pdfplumber.open(path)
    except PdfminerException as error:
        raise ValueError('Cannot read this PDF. Use an unencrypted, readable bank PDF.') from error
    with document as pdf:
        if not pdf.pages:
            raise ValueError('Statement PDF has no pages.')
        if resolve1(pdf.doc.catalog['Pages']).get('Count') != len(pdf.pages):
            raise ValueError('Inconsistent PDF page count; repeated or malformed pages are unsupported.')
        candidates = check_selection(pdf.pages[0].extract_text() or '', bank)
        if len(candidates) == 1:
            return read_bank(pdf, path, year, candidates[0])
        # Bank names inside transactions add candidates; only the real layout reconciles.
        passed, errors = [], []
        for candidate in candidates:
            try:
                passed.append(read_bank(pdf, path, year, candidate))
            except (ValueError, KeyError, IndexError) as error:
                errors.append(f'{BANKS[candidate]}: {error}')
    if len(passed) == 1:
        return passed[0]
    if passed:
        raise ValueError(f'This PDF passes the {names(r["bank"] for r in passed)} checks. Select the bank manually.')
    raise ValueError(f'This PDF names {names(candidates)}, but no layout passed its checks. ' + ' '.join(errors))


def main():
    """Extract a statement PDF into the bank master CSV (the year is required: dates print without it)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--year", type=int, required=True)
    from statement_extraction.formats import BANKS

    parser.add_argument('--bank', choices=['auto', *BANKS], default='auto')
    parser.add_argument("--output", type=Path, default=Path("bank-output"))
    args = parser.parse_args()
    try:
        result = extract(args.pdf, args.year, args.bank)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Extraction stopped: {error}\n")

    # The master CSV is the sole interchange file for matching and Excel export.
    args.output.mkdir(parents=True, exist_ok=True)
    write_master(result, args.output / "master_statement.csv")
    print(f"Extracted {len(result['transactions'])} transactions; all balance and total checks passed.")
    print(
        f"Opening: {result['opening_balance']} | In: {result['total_money_in']} | "
        f"Out: {result['total_money_out']} | Closing: {result['closing_balance']}"
    )
    print(f"Output: {args.output.resolve()}")
    if result.get('validation_note'):
        print(result['validation_note'])


if __name__ == "__main__":
    main()
