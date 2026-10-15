"""Read the observed single-account AmBank MYR digital layout."""

import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from reconciliation.bank.statement import amount, cell, validate

#: AmBank digital statements are A4 portrait; column positions below assume this width (points).
A4_WIDTH = 595.28
#: Left edges (points) of each statement column; a column runs to the next edge.
DATE_X, NARRATION_X, DEBIT_X, CREDIT_X, BALANCE_X = 0, 100, 310, 395, 480


def describe(narration, money_in):
    """Separate AmBank comma-delimited party and reference fields."""
    parts = narration.split(",", 2)
    method = " ".join(parts[0].split())
    raw_party = parts[1].strip() if len(parts) > 1 else ""
    raw_details = parts[2].strip() if len(parts) > 2 else ""
    party = " ".join(raw_party.split())

    # Incoming company fields may include a numeric prefix and a LEVEL address.
    if method in ("INWARD IBG", "INWARD RENTAS /MISC CREDIT"):
        party = re.sub(r"^\d+\s+", "", party)
        party = re.split(r"\s+LEVEL\s+", party, maxsplit=1, flags=re.I)[0]
    role = "payer" if money_in else "recipient"
    if method.startswith("IBG OUTWARD RTN"):
        role = "original payment recipient"
    # Preserve reference line breaks; replacing them with spaces changes identifiers.
    details = raw_details
    return {
        "transaction_type": method,
        "counterparty": party,
        "counterparty_role": role,
        "counterparty_raw": raw_party,
        "details_raw": raw_details,
        "particular": details or method,
    }


def extract(path, year):
    """Read this AmBank layout; fail when required structure is missing."""
    rows = []
    opening = debit_total = credit_total = None
    account = None
    with pdfplumber.open(path) as pdf:
        # The cover summary supplies an independent closing balance.
        cover = pdf.pages[0].extract_text() or ""
        summary = re.findall(r"(\d{10,})\s+MYR\s+([\d,]+\.\d{2})", cover)
        if "AMBANK" not in cover or len(summary) != 1:
            raise ValueError("Expected a single-account AmBank MYR statement")
        account, closing_text = summary[0]
        closing = amount(closing_text)

        # Ignore non-transaction pages and repeated bilingual table headings.
        for page_number, page in enumerate(pdf.pages, 1):
            lines = page.extract_text_lines()
            if not lines:
                raise ValueError(f"Page {page_number} has no readable text; OCR required")
            header = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if line["text"] == "DATE TRANSACTION CHEQUE NO. DEBIT CREDIT BALANCE"
                ),
                None,
            )
            if header is None:
                if any(re.match(r"^\d{2}-[A-Za-z]{3}\s", line["text"]) for line in lines):
                    raise ValueError(f"Transaction-like page {page_number} has an unsupported header")
                continue
            if abs(page.width - A4_WIDTH) > 1:
                raise ValueError("Unsupported page width for AmBank column positions")
            for line in lines[header + 1 :]:
                text = line["text"]
                if text.startswith("TARIKH TRANSAKSI"):
                    continue
                if text.startswith("Balance Brought Fwd"):
                    if opening is not None:
                        raise ValueError("Multiple opening balances are unsupported")
                    opening = amount(cell(line, BALANCE_X, page.width))
                    continue
                if text.startswith("TOTAL / JUMLAH"):
                    debit_total = amount(cell(line, DEBIT_X, CREDIT_X))
                    credit_total = amount(cell(line, CREDIT_X, BALANCE_X))
                    break

                # A date begins a transaction; subsequent lines extend its narration.
                date_text = cell(line, DATE_X, NARRATION_X)
                narration = cell(line, NARRATION_X, DEBIT_X)
                debit = cell(line, DEBIT_X, CREDIT_X)
                credit = cell(line, CREDIT_X, BALANCE_X)
                balance = cell(line, BALANCE_X, page.width)
                if re.fullmatch(r"\d{2}-[A-Za-z]{3}", date_text):
                    if bool(debit) == bool(credit):
                        raise ValueError(f"Expected one debit or credit on page {page_number}")
                    rows.append(
                        {
                            "date": datetime.strptime(f"{date_text}-{year}", "%d-%b-%Y").date().isoformat(),
                            "narration": narration,
                            "money_out": amount(debit) if debit else Decimal("0.00"),
                            "money_in": amount(credit) if credit else Decimal("0.00"),
                            "balance": amount(balance),
                            "page": page_number,
                        }
                    )
                elif not date_text and not (debit or credit or balance) and narration and rows:
                    rows[-1]["narration"] += "\n" + narration
                else:
                    raise ValueError(f"Unrecognized transaction line on page {page_number}: {text}")

    # Only reconciled records can reach the output stage.
    validate(rows, opening, closing, debit_total, credit_total)
    return {
        "source": str(path.resolve()),
        "bank": "ambank",
        "account": account,
        "currency": "MYR",
        "year_supplied": year,
        "opening_balance": opening,
        "closing_balance": closing,
        "total_money_in": credit_total,
        "total_money_out": debit_total,
        "balance_checks": "passed",
        "transactions": rows,
    }
