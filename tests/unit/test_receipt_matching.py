"""Exercise multiple receipts per image and audited bank allocation decisions."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dashboard import receipt_review
from reconciliation.duplicate_workflow import fingerprint


class ReceiptMatchingTests(unittest.TestCase):
    def setUp(self):
        """Create two pieces in one source image and three independent bank entries."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.review = SimpleNamespace(manifest_path=self.base / "manifest.json")
        self.work = self.base / "review"
        self.work.mkdir()
        self.source = self.base / "photo.png"
        self.source.write_bytes(b"two separate receipt images")
        self.digest = fingerprint(self.source)
        self.key = self.digest + ":0"
        self.pieces = [{"location": location, "document_type": "receipt", "invoice_numbers": [],
                        "brief_description": description, "total": total, "currency": "MYR", "limitations": []}
                       for location, description, total in (("top", "Office supplies", "45.00"),
                                                            ("bottom", "Delivery", "15.00"))]
        self.index = {"manifest": str(self.review.manifest_path), "documents": {self.digest: {
            "paths": [str(self.source)], "error": None, "units": [{"label": "image 1", "image": None}]}}}
        (self.work / "index.json").write_text(json.dumps(self.index))
        self.state = {"index_sha256": fingerprint(self.work / "index.json"), "decisions": {},
                      "units": {self.key: {"readable": True, "receipts": self.pieces}}}
        self.save_state()
        bank = self.base / "bank.pdf"
        bank.write_bytes(b"original bank statement")
        (self.base / "bank-output").mkdir()
        with (self.base / "bank-output/master_statement.csv").open("w", newline="") as stream:
            fields = ["transaction_id", "source", "source_sha256", "currency", "money_in", "money_out", "balance_checks"]
            writer = csv.DictWriter(stream, fields)
            writer.writeheader()
            for key, total in (("combined", "60.00"), ("first", "45.00"), ("second", "15.00")):
                writer.writerow({"transaction_id": key, "source": str(bank), "source_sha256": fingerprint(bank),
                                 "currency": "MYR", "money_in": "0.00", "money_out": total, "balance_checks": "passed"})

    def save_state(self):
        """Publish a changed synthetic extraction checkpoint."""
        (self.work / "state.json").write_text(json.dumps(self.state))

    def view(self):
        """Read the current persisted review and revision."""
        return receipt_review.snapshot(self.review)

    def accept_pieces(self, pieces=None):
        """Explicitly accept the supplied extraction as a named fixture reviewer."""
        return receipt_review.accept_extraction(self.review, {"revision": self.view()["revision"],
            "key": self.key, "receipts": self.pieces if pieces is None else pieces, "reviewer": "Tester"})

    def test_accept_extraction_without_reviewer_keeps_audit_history(self):
        """Removing the name field still records the explicit approval and its time."""
        receipt_review.accept_extraction(self.review, {"revision": self.view()["revision"],
            "key": self.key, "receipts": self.pieces})
        saved = json.loads((self.work / "receipt-matches.json").read_text())
        self.assertEqual(saved["history"][-1]["action"], "accept_extraction")
        self.assertIsNone(saved["history"][-1]["reviewer"])
        self.assertTrue(saved["history"][-1]["at"])

    def change(self, bank, action, items=None, reason=""):
        """Submit one revision-checked match action."""
        return receipt_review.change_match(self.review, {"revision": self.view()["revision"],
            "bank_transaction_id": bank, "action": action, "reviewer": "Tester", "reason": reason,
            "supporting_items": [{"receipt_id": f"{self.digest}:u0:r{number}", "allocated_amount": value}
                                 for number, value in items or []]})

    def test_combined_match_is_pending_until_acceptance_and_survives_reload(self):
        """Two pieces support one bank entry without merging their underlying records."""
        self.accept_pieces()
        view = self.change("combined", "propose", [(0, "45.00"), (1, "15.00")])
        match = view["matches"][0]
        self.assertEqual((match["supporting_total"], match["difference"], match["review_status"]), ("60.00", "0.00", "pending"))
        self.assertEqual([r["remaining_amount"] for r in view["receipts"]], ["45.00", "15.00"])
        self.change("combined", "accept")
        self.assertEqual([r["remaining_amount"] for r in self.view()["receipts"]], ["0.00", "0.00"])
        self.assertEqual(len(self.view()["units"][0]["receipts"]), 2)
        self.assertEqual(self.source.read_bytes(), b"two separate receipt images")
        self.change("combined", "undo")
        self.assertEqual(self.view()["receipts"][0]["remaining_amount"], "45.00")
        history = json.loads((self.work / "receipt-matches.json").read_text())["history"]
        self.assertEqual([entry["action"] for entry in history], ["accept_extraction", "propose", "accept", "undo"])

    def test_separate_bank_entries_use_separate_receipts_from_same_photo(self):
        """Each piece can independently support its corresponding bank transaction."""
        self.accept_pieces()
        self.change("first", "propose", [(0, "45.00")])
        self.change("first", "accept")
        self.change("second", "propose", [(1, "15.00")])
        self.change("second", "accept")
        self.assertEqual([m["difference"] for m in self.view()["matches"]], ["0.00", "0.00"])

    def test_pending_proposals_cannot_double_allocate_on_acceptance(self):
        """Recheck remaining amounts after another pending proposal is accepted."""
        self.accept_pieces()
        self.change("combined", "propose", [(0, "45.00"), (1, "15.00")])
        self.change("first", "propose", [(0, "45.00")])
        self.change("combined", "accept")
        with self.assertRaisesRegex(ValueError, "remaining amount"):
            self.change("first", "accept")
        with self.assertRaisesRegex(ValueError, "Undo accepted matches"):
            self.accept_pieces()

    def test_partial_allocations_and_discrepancies_remain_explicit(self):
        """One receipt can cover instalments without hiding an amount difference."""
        self.accept_pieces()
        self.change("second", "propose", [(0, "15.00")])
        self.change("second", "accept")
        self.change("first", "propose", [(0, "30.00")])
        with self.assertRaisesRegex(ValueError, "Explain the amount difference"):
            self.change("first", "accept")
        view = self.change("first", "accept", reason="Remaining support is missing")
        self.assertEqual(view["matches"][1]["difference"], "15.00")
        self.assertEqual(view["receipts"][0]["remaining_amount"], "0.00")

    def test_missing_values_currency_and_duplicate_ids_are_not_guessed(self):
        """Unapproved, incomplete, mixed-currency, or repeated pieces cannot allocate."""
        with self.assertRaisesRegex(ValueError, "accept the receipt"):
            self.change("first", "propose", [(0, "45.00")])
        self.accept_pieces()
        with self.assertRaisesRegex(ValueError, "only once"):
            self.change("first", "propose", [(0, "15.00"), (0, "15.00")])
        self.pieces[0]["currency"] = "USD"
        self.accept_pieces()
        with self.assertRaisesRegex(ValueError, "currencies differ"):
            self.change("first", "propose", [(0, "45.00")])
        self.pieces[0].update(total="", currency="MYR")
        self.accept_pieces()
        with self.assertRaisesRegex(ValueError, "Enter an amount"):
            self.change("first", "propose", [(0, "45.00")])
        self.assertEqual(self.view()["receipts"][0]["total"], "")

    def test_changed_extraction_and_source_bytes_block_acceptance(self):
        """Refresh or source tampering cannot silently preserve a proposal's evidence."""
        self.accept_pieces()
        self.change("combined", "propose", [(0, "45.00"), (1, "15.00")])
        self.source.write_bytes(b"changed")
        self.assertTrue(self.view()["matches"][0]["stale"])
        with self.assertRaisesRegex(ValueError, "current pending"):
            self.change("combined", "accept")
        self.source.write_bytes(b"two separate receipt images")
        self.state["units"][self.key]["receipts"][0]["total"] = "40.00"
        self.save_state()
        self.assertTrue(self.view()["matches"][0]["stale"])
        with self.assertRaisesRegex(ValueError, "current pending"):
            self.change("combined", "accept")

    def test_stale_browser_submission_and_negative_amount_fail(self):
        """Prevent lost updates and invalid monetary input without writing a match."""
        old = self.view()["revision"]
        self.accept_pieces()
        with self.assertRaisesRegex(ValueError, "reload"):
            receipt_review.accept_extraction(self.review, {"revision": old})
        for invalid in ("-1", "NaN", "1.001", ""):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.change("first", "propose", [(0, invalid)])

    def test_changed_bank_source_marks_match_stale_but_keeps_undo_available(self):
        """Do not silently preserve approval after the original bank evidence changes."""
        self.accept_pieces()
        self.change("combined", "propose", [(0, "45.00"), (1, "15.00")])
        self.change("combined", "accept")
        (self.base / "bank.pdf").write_bytes(b"replaced bank statement")
        view = self.view()
        self.assertTrue(view["matches"][0]["stale"])
        self.assertEqual(view["receipts"][0]["remaining_amount"], "0.00")
        self.change("combined", "undo")
        self.assertEqual(self.view()["receipts"][0]["remaining_amount"], "45.00")
