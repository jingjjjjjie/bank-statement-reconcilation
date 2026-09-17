"""Extract and reconcile a single-account AmBank digital statement locally."""

import argparse
import csv
import hashlib
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber

# Keep money exact and retain the evidence needed for later matching.
MONEY = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}")
MASTER_FIELDS = ("transaction_id,source,source_sha256,page,sequence,account,currency,"
                 "year_supplied,date,direction,money_in,money_out,balance,"
                 "transaction_type,counterparty,counterparty_role,counterparty_raw,"
                 "details_raw,particular,narration,opening_balance,closing_balance,"
                 "total_money_in,total_money_out,balance_checks,matching_status").split(",")


def describe(narration, money_in):
    """Separate comma-delimited AmBank fields while keeping original evidence."""
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
    return {"transaction_type": method, "counterparty": party,
            "counterparty_role": role, "counterparty_raw": raw_party,
            "details_raw": raw_details, "particular": details or method}


def write_master(result, path):
    """Write a self-contained CSV master, including statement-level checks."""
    metadata = {k: v for k, v in result.items() if k != "transactions"}
    metadata["source_sha256"] = hashlib.sha256(Path(result["source"]).read_bytes()).hexdigest()
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=MASTER_FIELDS)
        writer.writeheader()
        for sequence, row in enumerate(result["transactions"], 1):
            writer.writerow({**metadata, **row, **describe(row["narration"], row["money_in"]),
                             "sequence": sequence,
                             "transaction_id": f"{metadata['source_sha256']}:{sequence:04d}",
                             "direction": "in" if row["money_in"] else "out",
                             "matching_status": "pending"})


def read_master(path):
    """Validate the master before producing an answer workbook."""
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ValueError("Master CSV contains no transactions")
    summary_keys = ("source", "source_sha256", "account", "currency", "year_supplied",
                    "opening_balance", "closing_balance", "total_money_in", "total_money_out")
    for row in rows:
        if any(row[k] != rows[0][k] for k in summary_keys):
            raise ValueError("Inconsistent statement metadata in master CSV")
        for key in ("money_in", "money_out", "balance"):
            row[key] = amount(row[key])
    result = {key: rows[0][key] for key in summary_keys}
    validate(rows, *(amount(result[k]) for k in
                    ("opening_balance", "closing_balance", "total_money_out", "total_money_in")))

    # Bind each CSV row to the unchanged PDF, not merely to plausible arithmetic.
    source = Path(result["source"])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != result["source_sha256"]:
        raise ValueError("Source PDF fingerprint changed")
    original = extract(source, int(result["year_supplied"]))
    for key in ("account", "currency"):
        if result[key] != original[key]:
            raise ValueError(f"Master {key} differs from source PDF")
    if len(rows) != len(original["transactions"]):
        raise ValueError("Master row count differs from source PDF")
    for number, (row, expected) in enumerate(zip(rows, original["transactions"]), 1):
        derived = describe(expected["narration"], expected["money_in"])
        required = {**expected, **derived, "sequence": number,
                    "transaction_id": f"{digest}:{number:04d}",
                    "direction": "in" if expected["money_in"] else "out"}
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
    """Read a column using the observed AmBank page coordinates."""
    chars = [c for c in line["chars"] if left <= c["x0"] < right]
    return pdfplumber.utils.extract_text(chars, x_tolerance=1).strip() if chars else ""


def validate(rows, opening, closing, debit_total, credit_total):
    """Check each balance and both independent printed monthly totals."""
    if not rows or any(v is None for v in (opening, closing, debit_total, credit_total)):
        raise ValueError("Missing transactions, opening/closing balance, or printed totals")
    balance = opening
    for number, row in enumerate(rows, 1):
        if min(row["money_in"], row["money_out"]) < 0 or bool(row["money_in"]) == bool(row["money_out"]):
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
            header = next((i for i, line in enumerate(lines)
                           if line["text"] == "DATE TRANSACTION CHEQUE NO. DEBIT CREDIT BALANCE"), None)
            if header is None:
                if any(re.match(r"^\d{2}-[A-Za-z]{3}\s", line["text"]) for line in lines):
                    raise ValueError(f"Transaction-like page {page_number} has an unsupported header")
                continue
            if abs(page.width - 595.28) > 1:
                raise ValueError("Unsupported page width for AmBank column positions")
            for line in lines[header + 1:]:
                text = line["text"]
                if text.startswith("TARIKH TRANSAKSI"):
                    continue
                if text.startswith("Balance Brought Fwd"):
                    if opening is not None:
                        raise ValueError("Multiple opening balances are unsupported")
                    opening = amount(cell(line, 480, page.width))
                    continue
                if text.startswith("TOTAL / JUMLAH"):
                    debit_total = amount(cell(line, 310, 395))
                    credit_total = amount(cell(line, 395, 480))
                    break

                # A date begins a transaction; subsequent lines extend its narration.
                date_text = cell(line, 0, 100)
                narration = cell(line, 100, 310)
                debit = cell(line, 310, 395)
                credit = cell(line, 395, 480)
                balance = cell(line, 480, page.width)
                if re.fullmatch(r"\d{2}-[A-Za-z]{3}", date_text):
                    if bool(debit) == bool(credit):
                        raise ValueError(f"Expected one debit or credit on page {page_number}")
                    rows.append({
                        "date": datetime.strptime(f"{date_text}-{year}", "%d-%b-%Y").date().isoformat(),
                        "narration": narration,
                        "money_out": amount(debit) if debit else Decimal("0.00"),
                        "money_in": amount(credit) if credit else Decimal("0.00"),
                        "balance": amount(balance),
                        "page": page_number,
                    })
                elif not date_text and not (debit or credit or balance) and narration and rows:
                    rows[-1]["narration"] += "\n" + narration
                else:
                    raise ValueError(f"Unrecognized transaction line on page {page_number}: {text}")

    # Only reconciled records can reach the output stage.
    validate(rows, opening, closing, debit_total, credit_total)
    return {"source": str(path.resolve()), "account": account, "currency": "MYR",
            "year_supplied": year, "opening_balance": opening, "closing_balance": closing,
            "total_money_in": credit_total, "total_money_out": debit_total,
            "balance_checks": "passed", "transactions": rows}


def main():
    # Require the year explicitly because the sample's date header overlaps itself.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output", type=Path, default=Path("bank-output"))
    args = parser.parse_args()
    try:
        result = extract(args.pdf, args.year)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Extraction stopped: {error}\n")

    # The master CSV is the sole interchange file for matching and Excel export.
    args.output.mkdir(parents=True, exist_ok=True)
    write_master(result, args.output / "master_statement.csv")
    print(f"Extracted {len(result['transactions'])} transactions; all balance and total checks passed.")
    print(f"Opening: {result['opening_balance']} | In: {result['total_money_in']} | "
          f"Out: {result['total_money_out']} | Closing: {result['closing_balance']}")
    print(f"Output: {args.output.resolve()}")


if __name__ == "__main__":
    main()
