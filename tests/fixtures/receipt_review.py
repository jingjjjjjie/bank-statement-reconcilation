"""Fixture: One source image with two receipt pieces, its prepared review, and a three-line bank master."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dashboard.services import receipt_review
from reconciliation.intake.duplicates import fingerprint


class ReceiptReviewFixture(unittest.TestCase):
    """Reusable setUp and helpers; subclass it, or instantiate and call setUp() inside another test."""

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

    def seed_accepted_allocation(self):
        """Write an accepted bank allocation as saved by the retired receipt-matching page."""
        path = self.work / "receipt-matches.json"
        saved = json.loads(path.read_text()) if path.exists() else {"extractions": {}, "matches": {}, "history": []}
        saved["matches"]["combined"] = {"review_status": "accepted", "supporting_items": [{"document_id": self.digest}]}
        path.write_text(json.dumps(saved))

    def clear_allocations(self):
        """Remove saved allocations, as undoing them would."""
        path = self.work / "receipt-matches.json"
        saved = json.loads(path.read_text())
        saved["matches"] = {}
        path.write_text(json.dumps(saved))

