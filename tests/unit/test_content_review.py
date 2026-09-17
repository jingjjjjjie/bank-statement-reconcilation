"""Pass-two dashboard fixtures verify gating and explicit human decisions."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from reconciliation.codex_reviewer import COMPARISON, EXTRACTION, ReviewCancelled, SCREEN
from dashboard.app import Review, handler_for
from dashboard import content_review, development
from reconciliation.duplicate_workflow import organize
from reconciliation.vision_workflow import load, run


class FixtureReviewer:
    """Return structured fixtures without using Codex or subscription tokens."""

    model = "fixture"

    def ask(self, prompt, schema, images=()):
        """Produce matching fields and a comparison requiring admin review."""
        if schema == EXTRACTION:
            return {"receipts": [], "readable": True, "supporting_evidence_status": "potential_support",
                    "supporting_evidence_reason": "Visible transaction details", "document_type": "invoice", "receipt_status": "not_receipt", "invoice_numbers": ["INV-1"],
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
        mode = patch("reconciliation.development_cache.mode", return_value={"enabled": True})
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
        prepared = get("/api/content-review")
        self.assertTrue(prepared["prepared"])
        self.assertEqual(prepared["documents_read"], 0)
        self.assertGreater(prepared["units_total"], 0)
        work = self.manifest.parent / "review"
        index, state = load(work)
        run(work, index, state, FixtureReviewer())
        extracted = get("/api/content-review")
        self.assertEqual(extracted["documents_read"], extracted["documents"])
        self.assertEqual(extracted["units_read"], extracted["units_total"])
        candidate = get("/api/content-review")["pairs"][0]
        self.assertIsNone(candidate["decision"])
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(base + "/api/content/decide", b"{}"))
        self.assertEqual(error.exception.code, 403)
        post("/api/content/decide", {"pair": candidate["pair"], "verdict": "keep_left",
             "reviewer": "Admin", "reason": "Same complete document"})
        decided = get("/api/content-review")["pairs"][0]
        self.assertEqual(decided["decision"]["reviewer"], "Admin")
        self.assertEqual(post("/api/development/remember", {})["content"], 1)
        post("/api/content/undo", {"pair": candidate["pair"], "reviewer": "Admin",
             "reason": "Need to inspect the source again"})
        self.assertIsNone(get("/api/content-review")["pairs"][0]["decision"])
        _, reverted = load(work)
        self.assertIsNone(reverted["decision_history"][-1]["verdict"])
        self.assertTrue(reverted["decision_history"][-1]["previous"])
        replayed = post("/api/development/apply", {"reviewer": "Tester"})
        self.assertEqual(replayed["content_applied"], 1)
        self.assertEqual(get("/api/content-review")["pairs"][0]["decision"]["reviewer"], "Tester")
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

    def test_stop_keeps_incomplete_work_pending(self):
        """A stop request cancels the active batch without saving partial evidence."""
        content_review.prepare(self.review)
        started = threading.Event()
        cancelled = threading.Event()

        class BlockingReviewer(FixtureReviewer):
            def ask(self, prompt, schema, images=()):
                started.set()
                cancelled.wait(timeout=5)
                raise ReviewCancelled("stopped")

            def cancel(self):
                cancelled.set()

        with patch("dashboard.content_review.CodexReviewer", side_effect=lambda *args, **kwargs: BlockingReviewer()):
            content_review.start(self.review)
            self.assertTrue(started.wait(timeout=5))
            self.assertTrue(content_review.stop(self.review)["stop_requested"])
            self.review.content_thread.join(timeout=5)
        self.assertFalse(self.review.content_thread.is_alive())
        self.assertEqual(load(self.manifest.parent / "review")[1]["units"], {})
        self.assertIn("stopped", content_review.snapshot(self.review)["run_error"])

    def test_stopped_requires_worker_finalization_and_verified_exit(self):
        """Keep Stop pending until the worker finishes its final checkpoint writes."""
        self.review.content_cancel = threading.Event()
        self.review.content_cancel.set()
        self.review.content_engine = SimpleNamespace(active_count=0)
        self.review.content_thread = SimpleNamespace(is_alive=lambda: True)
        self.assertEqual(content_review.execution_status(self.review)["execution_status"], "stopping")
        self.review.content_thread = SimpleNamespace(is_alive=lambda: False)
        self.assertEqual(content_review.execution_status(self.review)["execution_status"], "stopped")

    def test_unverified_process_prevents_restart_after_worker_exits(self):
        """Expose shutdown failures and retain the engine that owns remaining processes."""
        self.review.content_cancel = threading.Event()
        self.review.content_cancel.set()
        self.review.content_engine = SimpleNamespace(active_count=1)
        self.review.content_thread = SimpleNamespace(is_alive=lambda: False)
        status = content_review.execution_status(self.review)
        self.assertEqual(status["execution_status"], "stop_failed")
        self.assertTrue(status["running"])
        self.assertIn("could not be verified", status["run_error"])
        with self.assertRaisesRegex(ValueError, "already running"):
            content_review.start(self.review)


if __name__ == "__main__":
    unittest.main()
