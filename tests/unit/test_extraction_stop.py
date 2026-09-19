"""Exercise stop priority and races without calling the model service."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Depends

from dashboard.routes import context, create_app
from reconciliation.codex_reviewer import CodexReviewer, object_schema
from reconciliation.process_manager import ReviewCancelled
from reconciliation.vision_workflow import run_jobs
from tests.http_server import TestServer


class ExtractionStopTests(unittest.TestCase):
    def test_stop_bypasses_busy_dashboard_and_checks_review_identity(self):
        """A document scan cannot queue Stop behind the global request lock."""
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        review = SimpleNamespace(content_cancel=cancelled, content_engine=None,
                                 content_thread=SimpleNamespace(is_alive=lambda: not cancelled.is_set()))
        app = create_app(token="test-token")
        app.state.context.review = review

        @app.get("/api/test-block")
        def blocked(state=Depends(context)):
            """Hold the same lock used by document reads until the test releases it."""
            entered.set()
            release.wait(5)
            return {}

        app.router.routes.insert(0, app.router.routes.pop())
        server = TestServer(("127.0.0.1", 0), app)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with ThreadPoolExecutor(1) as pool:
                waiting = pool.submit(urllib.request.urlopen, base + "/api/test-block")
                try:
                    self.assertTrue(entered.wait(3))
                    headers = {"X-Review-Token": "test-token", "X-Review-Id": "stale"}
                    request = urllib.request.Request(base + "/api/content/stop", b"{}", headers)
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(request, timeout=1)
                    self.assertEqual(error.exception.code, 409)
                    self.assertFalse(cancelled.is_set())
                    request.add_header("X-Review-Id", app.state.context.review_id)
                    started = monotonic()
                    with urllib.request.urlopen(request, timeout=1) as response:
                        result = json.load(response)
                    self.assertTrue(result["stop_requested"])
                    self.assertLess(monotonic() - started, 1)
                    with urllib.request.urlopen(base + "/api/content/execution", timeout=1) as response:
                        self.assertEqual(json.load(response)["execution_status"], "stopped")
                finally:
                    release.set()
                    waiting.result(timeout=3).close()
        finally:
            server.shutdown()
            server.server_close()

    def test_late_results_never_reach_checkpoint(self):
        """Reject results returned after Stop with either serial or parallel workers."""
        for workers in (1, 3):
            with self.subTest(workers=workers), tempfile.TemporaryDirectory() as folder:
                reviewer = CodexReviewer(Path(folder))
                applied = []

                def late_result():
                    """Simulate a worker that ignores cancellation and returns anyway."""
                    reviewer.cancel()
                    return "late result"

                with self.assertRaises(ReviewCancelled):
                    run_jobs([late_result] * 5, applied.append, workers, acceptance=reviewer.acceptance)
                self.assertEqual(applied, [])

    def test_stop_during_validation_prevents_result_cache(self):
        """A successful process exit is insufficient if Stop arrives before publication."""
        with tempfile.TemporaryDirectory() as folder:
            reviewer = CodexReviewer(Path(folder))
            reviewer._login_checked[0] = True

            def completed(command, **kwargs):
                """Return valid output as if the CLI had just completed."""
                Path(command[command.index("--output-last-message") + 1]).write_text('{"ok":true}')
                return SimpleNamespace(returncode=0)

            with patch.object(reviewer.processes, "run", completed), \
                    patch("reconciliation.codex_reviewer.validate", side_effect=lambda *args: reviewer.cancel()):
                with self.assertRaises(ReviewCancelled):
                    reviewer.ask("test", object_schema({"ok": {"type": "boolean"}}))
            self.assertFalse(list(reviewer.cache.glob("*/result.json")))
