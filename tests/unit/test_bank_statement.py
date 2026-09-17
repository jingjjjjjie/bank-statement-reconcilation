"""Check counterparty boundaries and financial validation failures."""

import unittest
import csv
import tempfile
from pathlib import Path
from decimal import Decimal as D
from unittest.mock import patch

from reconciliation.bank_statement import describe, validate, read_master, write_master


class BankStatementTests(unittest.TestCase):
    # Keep wrapped names together without consuming the payment particulars.
    def test_wrapped_name(self):
        row = describe("Fund Transfer /DEBIT\nTRANSFER, WU WENJUN,\nCanva zuotufei", D("0"))
        self.assertEqual(row["counterparty"], "WU WENJUN")
        self.assertEqual(row["particular"], "Canva zuotufei")
        self.assertEqual(row["counterparty_role"], "recipient")

    # Retain bank address evidence while separating it from the display name.
    def test_incoming_address(self):
        row = describe("INWARD RENTAS /MISC CREDIT, 110172001 Yihai\nMalaysia Food Sdn Bhd LEVEL 6+MENARA 1, REF", D("10"))
        self.assertEqual(row["counterparty"], "Yihai Malaysia Food Sdn Bhd")
        self.assertIn("LEVEL", row["counterparty_raw"])
        self.assertEqual(row["counterparty_role"], "payer")

    # A return names the original payment recipient, not a new payer.
    def test_return_and_missing_party(self):
        row = describe("IBG OUTWARD RTN /INWARD IBG, Nur Nilam Sari B, R04 Invalid Acc No", D("10"))
        self.assertEqual(row["counterparty_role"], "original payment recipient")
        self.assertEqual(row["counterparty"], "Nur Nilam Sari B")
        self.assertEqual(describe("BANK CHARGE", D("0"))["counterparty"], "")

    # Reject a damaged running balance even when the input rows look valid.
    def test_balance_mismatch(self):
        row = {"money_in": D("5"), "money_out": D("0"), "balance": D("99"), "page": 2}
        with self.assertRaisesRegex(ValueError, "Balance mismatch"):
            validate([row], D("10"), D("15"), D("0"), D("5"))

    # A reference wrapping at the page width must not acquire an extra space.
    def test_wrapped_reference_is_preserved(self):
        row = describe("DuitNow CR TRF /MISC CREDIT, MONEYMATCH SDN BHD,\nMMCGV4UGQ6DM90VUL69Y\nH9D00AT1, 28255609", D("310.90"))
        self.assertEqual(row["particular"], "MMCGV4UGQ6DM90VUL69Y\nH9D00AT1, 28255609")

    # Empty or two-sided transactions can conceal errors despite balancing.
    def test_invalid_direction(self):
        for incoming, outgoing in ((D("0"), D("0")), (D("5"), D("5")), (D("-1"), D("0"))):
            with self.subTest(incoming=incoming, outgoing=outgoing):
                row = {"money_in": incoming, "money_out": outgoing, "balance": D("10"), "page": 2}
                with self.assertRaisesRegex(ValueError, "positive debit or credit"):
                    validate([row], D("10"), D("10"), outgoing, incoming)

    # A correct closing balance does not excuse incorrect printed monthly totals.
    def test_printed_total_mismatch(self):
        row = {"money_in": D("5.00"), "money_out": D("0.00"), "balance": D("15.00"), "page": 2}
        with self.assertRaisesRegex(ValueError, "credit total mismatch"):
            validate([row], D("10.00"), D("15.00"), D("0.00"), D("5.01"))

    def test_closing_balance_mismatch(self):
        row = {"money_in": D("5.00"), "money_out": D("0.00"), "balance": D("15.00"), "page": 2}
        with self.assertRaisesRegex(ValueError, "Closing balance mismatch"):
            validate([row], D("10.00"), D("15.01"), D("0.00"), D("5.00"))


class MasterIntegrityTests(unittest.TestCase):
    # Synthetic source results isolate CSV tampering checks from PDF extraction.
    def setUp(self):
        temporary_root = Path(__file__).resolve().parents[2] / ".tools" / "bank-tests"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "source.pdf"
        self.source.write_bytes(b"synthetic source fingerprint")
        self.master = self.root / "master.csv"
        self.result = {"source": str(self.source), "account": "123", "currency": "MYR",
                       "year_supplied": 2025, "opening_balance": D("100.00"),
                       "closing_balance": D("80.00"), "total_money_in": D("0.00"),
                       "total_money_out": D("20.00"), "balance_checks": "passed",
                       "transactions": [
                           {"date": "2025-12-01", "page": 2, "narration": "Fund Transfer /DEBIT TRANSFER, ALICE, REF1",
                            "money_in": D("0.00"), "money_out": D("10.00"), "balance": D("90.00")},
                           {"date": "2025-12-01", "page": 2, "narration": "Fund Transfer /DEBIT TRANSFER, BOB, REF2",
                            "money_in": D("0.00"), "money_out": D("10.00"), "balance": D("80.00")}]}
        write_master(self.result, self.master)
        mock = patch("reconciliation.bank_statement.extract", return_value=self.result)
        mock.start()
        self.addCleanup(mock.stop)

    # Rewrite a copy of the CSV to simulate an upstream or manual edit.
    def change(self, mutate):
        with self.master.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            fields, rows = reader.fieldnames, list(reader)
        mutate(rows)
        with self.master.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_untouched_master(self):
        self.assertEqual(len(read_master(self.master)["transactions"]), 2)

    # Swapping names on equal-value payments leaves every money check unchanged.
    def test_swapped_name(self):
        self.change(lambda rows: rows[0].update(counterparty="BOB"))
        with self.assertRaisesRegex(ValueError, "differs from source extraction"):
            read_master(self.master)

    def test_changed_narration(self):
        self.change(lambda rows: rows[0].update(narration="Fund Transfer /DEBIT TRANSFER, BOB, REF2"))
        with self.assertRaisesRegex(ValueError, "differs from source extraction"):
            read_master(self.master)

    def test_changed_date(self):
        self.change(lambda rows: rows[0].update(date="2024-12-01"))
        with self.assertRaisesRegex(ValueError, "differs from source extraction"):
            read_master(self.master)

    def test_duplicated_id(self):
        self.change(lambda rows: rows[1].update(transaction_id=rows[0]["transaction_id"]))
        with self.assertRaisesRegex(ValueError, "differs from source extraction"):
            read_master(self.master)

    def test_missing_row(self):
        self.change(lambda rows: rows.pop(0))
        with self.assertRaisesRegex(ValueError, "Balance mismatch"):
            read_master(self.master)

    def test_duplicate_row(self):
        self.change(lambda rows: rows.insert(1, dict(rows[0])))
        with self.assertRaisesRegex(ValueError, "Balance mismatch"):
            read_master(self.master)

    def test_modified_source(self):
        self.source.write_bytes(b"different PDF")
        with self.assertRaisesRegex(ValueError, "fingerprint changed"):
            read_master(self.master)

    def test_wrong_account(self):
        self.change(lambda rows: [row.update(account="OTHER") for row in rows])
        with self.assertRaisesRegex(ValueError, "account differs from source PDF"):
            read_master(self.master)




if __name__ == "__main__":
    unittest.main()
