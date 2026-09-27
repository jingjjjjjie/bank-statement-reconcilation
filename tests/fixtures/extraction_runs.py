"""Fixture: A two-image project with dashboard Review state for background extraction runs."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from dashboard.app import Review, create_app
from dashboard.services import extraction_runs, receipt_review, regeneration
from reconciliation.extraction.pieces import EXTRACTION as PIECE_EXTRACTION
from reconciliation.extraction.workflow import load, run
from reconciliation.intake.duplicates import organize
from reconciliation.model.codex import EXTRACTION, ReviewCancelled
from tests.http_server import TestServer


class FixtureReviewer:
    """Return structured fixtures without using Codex or subscription tokens."""

    model = "fixture"

    def ask(self, prompt, schema, images=()):
        """Return a fixed extraction; any other request is a test failure."""
        if schema in (EXTRACTION, PIECE_EXTRACTION):
            return {"receipts": [], "readable": True, "supporting_evidence_status": "potential_support",
                    "supporting_evidence_reason": "Visible transaction details", "document_type": "invoice", "receipt_status": "not_receipt", "invoice_numbers": ["INV-1"],
                    "company": ["Example"], "brief_description": "Cleaning",
                    "references": ["INV-1"], "parties": ["Example"], "dates": [],
                    "amounts_and_currencies": ["MYR 100"],
                    "money": [{"amount": "100", "currency": "MYR", "role": "grand_total"}],
                    "details": "Cleaning", "annotations_and_signatures": "", "limitations": []}
        raise AssertionError("Unexpected model schema")


class ExtractionRunsFixture(unittest.TestCase):
    """Reusable setUp and helpers; subclass it, or instantiate and call setUp() inside another test."""

    def setUp(self):
        """Create two nonidentical image files in an isolated source folder."""
        mode = patch("reconciliation.core.development_cache.mode", return_value={"enabled": True})
        mode.start()
        self.addCleanup(mode.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        root = base / "sources"
        root.mkdir()
        Image.new("RGB", (20, 20), "white").save(root / "first.png")
        Image.new("RGB", (20, 20), "black").save(root / "second.png")
        self.manifest = base / "manifest.json"
        organize(root, self.manifest)
        (base / "review_config.json").write_text(json.dumps({"pdf_mode": "auto", "pictures_enabled": True,
            "codex_enabled": True, "max_calls": 20, "model": "", "reasoning": "default", "stages": {}}), encoding="utf-8")
        self.review = Review(self.manifest, base / "dashboard-data")

