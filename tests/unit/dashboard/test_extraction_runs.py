"""Dashboard extraction runs: prepare, background start, regeneration queue and Stop."""

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
from tests.fixtures.extraction_runs import ExtractionRunsFixture, FixtureReviewer
from tests.http_server import TestServer


class ContentPageTests(ExtractionRunsFixture):

    def test_prepare_endpoint_requires_token_and_prepares_locally(self):
        """Prepare is an authenticated action and makes no model calls."""
        server = TestServer(("127.0.0.1", 0), create_app(self.review, "test-token"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/api/content/prepare"
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(url, b"{}"))
        self.assertEqual(error.exception.code, 403)
        request = urllib.request.Request(url, b"{}", {"X-Review-Token": "test-token", "Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            self.assertTrue(json.load(response)["prepared"])
        index, state = load(self.manifest.parent / "review")
        self.assertEqual(len(index["documents"]), 2)
        self.assertEqual(state["units"], {})

    def test_pass_one_blocks_content_prepare(self):
        """A pending exact-copy group cannot start content review."""
        root = Path(self.review.root)
        (root / "copy.png").write_bytes((root / "first.png").read_bytes())
        self.assertTrue(extraction_runs.exact_problems(self.review))
        with self.assertRaisesRegex(ValueError, "Finish exact"):
            extraction_runs.prepare(self.review)

    def test_run_button_resumes_review_in_background(self):
        """Dashboard runs extract evidence without duplicate screening or comparison."""
        extraction_runs.prepare(self.review)
        with patch("dashboard.services.extraction_runs.CodexReviewer", side_effect=lambda *args, **kwargs: FixtureReviewer()):
            extraction_runs.start(self.review)
            self.review.content_thread.join(timeout=5)
        self.assertFalse(self.review.content_thread.is_alive())
        self.assertEqual(self.review.content_error, "")
        index, state = load(self.manifest.parent / "review")
        self.assertEqual(len(state["units"]), sum(len(doc["units"]) for doc in index["documents"].values()))
        self.assertTrue(self.review.workflow_checks()[1])

    def test_regeneration_joins_shared_parallel_worker(self):
        """Queue deduplicated requests during extraction without exceeding its pool."""
        config = json.loads(self.review.config_path.read_text(encoding="utf-8"))
        config["max_parallel"] = 2
        self.review.config_path.write_text(json.dumps(config), encoding="utf-8")
        extraction_runs.prepare(self.review)
        started, release = threading.Event(), threading.Event()
        lock = threading.Lock()
        prompts, active, peak = [], [0], [0]

        class ParallelReviewer(FixtureReviewer):
            def fork(self):
                """Share only fixture counters across parallel calls."""
                return self

            def ask(self, prompt, schema, images=()):
                """Block the first batch while HTTP-like requests queue regeneration."""
                with lock:
                    prompts.append(prompt)
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                    if active[0] == 2:
                        started.set()
                try:
                    if not release.wait(timeout=5):
                        raise AssertionError("Fixture batch was not released")
                    return super().ask(prompt, schema, images)
                finally:
                    with lock:
                        active[0] -= 1

        with patch("dashboard.services.extraction_runs.CodexReviewer", side_effect=lambda *args, **kwargs: ParallelReviewer()):
            extraction_runs.start(self.review)
            try:
                self.assertTrue(started.wait(timeout=5))
                digests = list(load(self.manifest.parent / "review")[0]["documents"])
                first = regeneration.enqueue(self.review, digests[0])[digests[0]]["id"]
                self.assertEqual(regeneration.enqueue(self.review, digests[0])[digests[0]]["id"], first)
                regeneration.enqueue(self.review, digests[1])
                self.assertTrue(all(job["status"] == "queued" for job in regeneration.snapshot(self.review).values()))
            finally:
                release.set()
                self.review.content_thread.join(timeout=10)
        self.assertFalse(self.review.content_thread.is_alive())
        self.assertEqual(self.review.content_error, "")
        self.assertEqual(peak[0], 2)
        self.assertEqual(len(prompts), 4)
        self.assertEqual(sum("Regeneration request:" in prompt for prompt in prompts), 2)
        self.assertTrue(all(job["status"] == "completed" for job in regeneration.snapshot(self.review).values()))

    def test_failed_regeneration_retains_results_and_requires_retry(self):
        """An unsuccessful fresh call preserves evidence but cannot be approved."""
        extraction_runs.prepare(self.review)
        work = self.manifest.parent / "review"
        index, state = load(work)
        run(work, index, state, FixtureReviewer())
        digest = next(iter(index["documents"]))
        before = load(work)[1]["units"]

        class FailedReviewer(FixtureReviewer):
            def ask(self, prompt, schema, images=()):
                """Fail without returning a fabricated extraction."""
                raise RuntimeError("Fixture model failure")

        with patch("dashboard.services.extraction_runs.CodexReviewer", side_effect=lambda *args, **kwargs: FailedReviewer()):
            regeneration.enqueue(self.review, digest)
            self.review.content_thread.join(timeout=5)
        self.assertEqual(load(work)[1]["units"], before)
        job = regeneration.snapshot(self.review)[digest]
        self.assertEqual(job["status"], "failed")
        self.assertIn("Fixture model failure", job["error"])
        data = receipt_review.snapshot(self.review)
        with self.assertRaisesRegex(ValueError, "Finish regeneration"):
            receipt_review.accept_extraction(self.review, {"revision": data["revision"], "key": digest + ":0", "receipts": []})

    def test_new_regeneration_uses_idle_parallel_slot(self):
        """A second click starts before the first model call finishes."""
        config = json.loads(self.review.config_path.read_text(encoding="utf-8"))
        config["max_parallel"] = 2
        self.review.config_path.write_text(json.dumps(config), encoding="utf-8")
        extraction_runs.prepare(self.review)
        work = self.manifest.parent / "review"
        index, state = load(work)
        run(work, index, state, FixtureReviewer())
        first, second, release = threading.Event(), threading.Event(), threading.Event()
        calls, lock = [], threading.Lock()

        class BlockingReviewer(FixtureReviewer):
            def fork(self):
                """Share the fixture's synchronization events."""
                return self

            def ask(self, prompt, schema, images=()):
                """Hold both calls until the test confirms parallel execution."""
                with lock:
                    calls.append(prompt)
                    (first if len(calls) == 1 else second).set()
                if not release.wait(timeout=5):
                    raise AssertionError("Parallel slot was not filled")
                return super().ask(prompt, schema, images)

        with patch("dashboard.services.extraction_runs.CodexReviewer", side_effect=lambda *args, **kwargs: BlockingReviewer()):
            digests = list(index["documents"])
            regeneration.enqueue(self.review, digests[0])
            try:
                self.assertTrue(first.wait(timeout=5))
                regeneration.enqueue(self.review, digests[1])
                self.assertTrue(second.wait(timeout=3))
            finally:
                release.set()
                self.review.content_thread.join(timeout=5)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(job["status"] == "completed" for job in regeneration.snapshot(self.review).values()))

    def test_regeneration_invalidates_approval_even_for_identical_output(self):
        """A fresh request requires review even if the model returns identical facts."""
        extraction_runs.prepare(self.review)
        work = self.manifest.parent / "review"
        index, state = load(work)
        run(work, index, state, FixtureReviewer())
        digest = next(iter(index["documents"]))
        data = receipt_review.snapshot(self.review)
        receipt_review.accept_extraction(self.review, {"revision": data["revision"], "key": digest + ":0", "receipts": []})
        with patch("dashboard.services.extraction_runs.CodexReviewer", side_effect=lambda *args, **kwargs: FixtureReviewer()):
            regeneration.enqueue(self.review, digest)
            self.review.content_thread.join(timeout=5)
        unit = next(unit for unit in receipt_review.snapshot(self.review)["units"] if unit["document_id"] == digest)
        self.assertFalse(unit["accepted"])
        self.assertEqual(unit["regeneration"]["status"], "completed")
        self.assertEqual(unit["supporting_evidence"][0]["status"], "potential_support")

    def test_interrupted_regeneration_is_unresolved(self):
        """Restarted servers expose unfinished durable jobs as retryable failures."""
        extraction_runs.prepare(self.review)
        regeneration.queue_path(self.review).write_text(json.dumps({"jobs": {
            "fixture": {"id": "attempt", "status": "running", "error": ""}}, "history": []}), encoding="utf-8")
        self.assertEqual(regeneration.snapshot(self.review)["fixture"]["status"], "failed")

    def test_stop_marks_running_regeneration_unresolved(self):
        """Cancellation retains the previous extraction and ends the live indicator."""
        extraction_runs.prepare(self.review)
        work = self.manifest.parent / "review"
        index, state = load(work)
        run(work, index, state, FixtureReviewer())
        before = load(work)[1]["units"]
        started, cancelled = threading.Event(), threading.Event()

        class CancelReviewer(FixtureReviewer):
            def ask(self, prompt, schema, images=()):
                """Hold the model call until cancellation is requested."""
                started.set()
                cancelled.wait(timeout=5)
                raise ReviewCancelled("stopped")

            def cancel(self):
                """Release the waiting fixture call."""
                cancelled.set()

        with patch("dashboard.services.extraction_runs.CodexReviewer", side_effect=lambda *args, **kwargs: CancelReviewer()):
            digest = next(iter(index["documents"]))
            regeneration.enqueue(self.review, digest)
            self.assertTrue(started.wait(timeout=5))
            extraction_runs.stop(self.review)
            self.review.content_thread.join(timeout=5)
        self.assertEqual(regeneration.snapshot(self.review)[digest]["status"], "failed")
        self.assertEqual(load(work)[1]["units"], before)

    def test_stop_keeps_incomplete_work_pending(self):
        """A stop request cancels the active batch without saving partial evidence."""
        extraction_runs.prepare(self.review)
        started = threading.Event()
        cancelled = threading.Event()

        class BlockingReviewer(FixtureReviewer):
            def ask(self, prompt, schema, images=()):
                started.set()
                cancelled.wait(timeout=5)
                raise ReviewCancelled("stopped")

            def cancel(self):
                cancelled.set()

        with patch("dashboard.services.extraction_runs.CodexReviewer", side_effect=lambda *args, **kwargs: BlockingReviewer()):
            extraction_runs.start(self.review)
            self.assertTrue(started.wait(timeout=5))
            self.assertTrue(extraction_runs.stop(self.review)["stop_requested"])
            self.review.content_thread.join(timeout=5)
        self.assertFalse(self.review.content_thread.is_alive())
        self.assertEqual(load(self.manifest.parent / "review")[1]["units"], {})
        self.assertIn("stopped", extraction_runs.execution_status(self.review)["run_error"])

    def test_stopped_requires_worker_finalization_and_verified_exit(self):
        """Keep Stop pending until the worker finishes its final checkpoint writes."""
        self.review.content_cancel = threading.Event()
        self.review.content_cancel.set()
        self.review.content_engine = SimpleNamespace(active_count=0)
        self.review.content_thread = SimpleNamespace(is_alive=lambda: True)
        self.assertEqual(extraction_runs.execution_status(self.review)["execution_status"], "stopping")
        self.review.content_thread = SimpleNamespace(is_alive=lambda: False)
        self.assertEqual(extraction_runs.execution_status(self.review)["execution_status"], "stopped")

    def test_unverified_process_prevents_restart_after_worker_exits(self):
        """Expose shutdown failures and retain the engine that owns remaining processes."""
        self.review.content_cancel = threading.Event()
        self.review.content_cancel.set()
        self.review.content_engine = SimpleNamespace(active_count=1)
        self.review.content_thread = SimpleNamespace(is_alive=lambda: False)
        status = extraction_runs.execution_status(self.review)
        self.assertEqual(status["execution_status"], "stop_failed")
        self.assertTrue(status["running"])
        self.assertIn("could not be verified", status["run_error"])
        with self.assertRaisesRegex(ValueError, "already running"):
            extraction_runs.start(self.review)


if __name__ == "__main__":
    unittest.main()
