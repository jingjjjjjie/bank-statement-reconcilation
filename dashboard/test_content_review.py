"""Pass-two dashboard fixtures verify gating and explicit human decisions."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from codex_reviewer import COMPARISON, EXTRACTION, SCREEN
from dashboard.app import Review, handler_for
from dashboard import content_review
from duplicate_workflow import organize
from vision_workflow import load, run


class FixtureReviewer:
    """Return structured fixtures without using Codex or subscription tokens."""

    model = "fixture"

    def ask(self, prompt, schema, images=()):
        """Produce matching fields and a comparison requiring admin review."""
        if schema == EXTRACTION:
            return {"readable": True, "document_type": "invoice", "receipt_status": "not_receipt", "invoice_numbers": ["INV-1"],
                    "company": ["Example"], "brief_description": "Cleaning",
                    "references": ["INV-1"], "parties": ["Example"], "dates": [],
                    "amounts_and_currencies": ["MYR 100"],
                    "money": [{"amount": "100", "currency": "MYR", "role": "grand_total"}],
                    "details": "Cleaning", "annotations_and_signatures": "", "limitations": []}
        if schema == SCREEN:
            raise AssertionError("Matching totals should skip model screening")
        if schema == COMPARISON:
            return {"classification": "same_document", "confidence": "high",
                    "evidence": ["Same invoice and total"], "differences": [], "limitations": []}
        raise AssertionError("Unexpected model schema")


class ContentPageTests(unittest.TestCase):
    def setUp(self):
        """Create two nonidentical image files in an isolated source folder."""
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

    def test_page_prepares_and_requires_admin_verdict(self):
        """The page lists model evidence and saves an explicit human decision."""
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.review, "test-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        def get(path):
            """Read JSON from one local dashboard endpoint."""
            with urllib.request.urlopen(base + path) as response:
                return json.load(response)

        def post(path, body):
            """Send an authenticated dashboard action."""
            request = urllib.request.Request(base + path, json.dumps(body).encode(),
                                             {"X-Review-Token": "test-token", "Content-Type": "application/json"})
            with urllib.request.urlopen(request) as response:
                return json.load(response)

        with urllib.request.urlopen(base + "/content-review") as response:
            self.assertIn(b"Review possible copies", response.read())
        self.assertFalse(get("/api/content-review")["prepared"])
        post("/api/content/prepare", {})
        self.assertTrue(get("/api/content-review")["prepared"])
        work = self.manifest.parent / "review"
        index, state = load(work)
        run(work, index, state, FixtureReviewer())
        candidate = get("/api/content-review")["pairs"][0]
        self.assertIsNone(candidate["decision"])
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(base + "/api/content/decide", b"{}"))
        self.assertEqual(error.exception.code, 403)
        post("/api/content/decide", {"pair": candidate["pair"], "verdict": "keep_left",
             "reviewer": "Admin", "reason": "Same complete document"})
        decided = get("/api/content-review")["pairs"][0]
        self.assertEqual(decided["decision"]["reviewer"], "Admin")
        post("/api/content/undo", {"pair": candidate["pair"], "reviewer": "Admin",
             "reason": "Need to inspect the source again"})
        self.assertIsNone(get("/api/content-review")["pairs"][0]["decision"])
        _, reverted = load(work)
        self.assertIsNone(reverted["decision_history"][-1]["verdict"])
        self.assertTrue(reverted["decision_history"][-1]["previous"])
        self.assertTrue(all(Path(path).is_file() for document in index["documents"].values()
                            for path in document["paths"]))

    def test_pass_one_blocks_content_prepare(self):
        """A pending exact-copy group cannot start content review."""
        root = Path(self.review.root)
        (root / "copy.png").write_bytes((root / "first.png").read_bytes())
        self.assertFalse(content_review.snapshot(self.review)["exact_ready"])
        with self.assertRaisesRegex(ValueError, "Finish exact"):
            content_review.prepare(self.review)

    def test_run_button_resumes_review_in_background(self):
        """Starting a batch returns promptly and saves comparable candidates."""
        content_review.prepare(self.review)
        with patch("dashboard.content_review.CodexReviewer", side_effect=lambda *args, **kwargs: FixtureReviewer()):
            content_review.start(self.review)
            self.review.content_thread.join(timeout=5)
        self.assertFalse(self.review.content_thread.is_alive())
        self.assertEqual(self.review.content_error, "")
        self.assertEqual(len(content_review.snapshot(self.review)["pairs"]), 1)


if __name__ == "__main__":
    unittest.main()
