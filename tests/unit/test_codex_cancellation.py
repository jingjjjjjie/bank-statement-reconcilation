"""Use a local fake CLI to test real reviewer cancellation and audit records."""
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch

from reconciliation.codex_reviewer import CodexReviewer, object_schema
from reconciliation.process_manager import ReviewCancelled, spawn
from reconciliation.token_usage import summary


CLI = """import pathlib, subprocess, sys, time
if sys.argv[1:3] == ['login', 'status']:
    print('ChatGPT', flush=True)
else:
    output = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])
    output.write_text('{"ok": true}')
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    output.with_suffix('.ready').write_text(str(child.pid))
    time.sleep(60)
"""


class CodexCancellationTests(unittest.TestCase):
    def test_parallel_stop_leaves_partial_responses_uncached_and_usage_unknown(self):
        """Verify shared ownership, rejected partial JSON, and durable cancelled attempts."""
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            script = work / "fake_cli.py"
            script.write_text(CLI, encoding="utf-8")
            reviewer = CodexReviewer(work / "review", executable="fixture", max_calls=3)
            workers = [reviewer.fork() for _ in range(3)]
            schema = object_schema({"ok": {"type": "boolean"}})

            def local_spawn(command, **kwargs):
                """Replace only the CLI executable; use real OS process management."""
                return spawn([sys.executable, str(script), *command[1:]], **kwargs)

            with patch("reconciliation.process_manager.spawn", local_spawn), ThreadPoolExecutor(3) as pool:
                futures = [pool.submit(worker.ask, f"fixture-{n}", schema) for n, worker in enumerate(workers)]
                try:
                    deadline = monotonic() + 5
                    while len(list(reviewer.cache.glob("*/*.ready"))) < 3 and monotonic() < deadline:
                        sleep(0.01)
                    self.assertEqual(len(list(reviewer.cache.glob("*/*.ready"))), 3)
                    self.assertEqual(reviewer.active_count, 3)
                finally:
                    reviewer.cancel()
                for future in futures:
                    with self.assertRaises(ReviewCancelled):
                        future.result(timeout=6)
            self.assertEqual(reviewer.active_count, 0)
            self.assertFalse(list(reviewer.cache.glob("*/result.json")))
            entries = [json.loads(line) for line in reviewer.usage_path.read_text().splitlines()]
            cancelled = [entry for entry in entries if entry["status"] == "cancelled"]
            self.assertEqual(len(cancelled), 3)
            self.assertTrue(all(entry["exit_verified"] and entry["pid"] for entry in cancelled))
            self.assertEqual(summary(reviewer.usage_path)["unknown_attempts"], 3)

    def test_stop_cancels_login_without_starting_exec(self):
        """The preliminary login check cannot hold Stop for its full timeout."""
        with tempfile.TemporaryDirectory() as temporary:
            reviewer = CodexReviewer(Path(temporary), executable="fixture")

            def local_spawn(command, **kwargs):
                """Simulate a hanging login using a real sleeping process."""
                return spawn([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)

            with patch("reconciliation.process_manager.spawn", local_spawn), ThreadPoolExecutor(1) as pool:
                future = pool.submit(reviewer.ask, "fixture", object_schema({"ok": {"type": "boolean"}}))
                try:
                    deadline = monotonic() + 3
                    while not reviewer.active_count and monotonic() < deadline:
                        sleep(0.01)
                    self.assertEqual(reviewer.active_count, 1)
                finally:
                    reviewer.cancel()
                with self.assertRaises(ReviewCancelled):
                    future.result(timeout=6)
            self.assertEqual((reviewer.active_count, reviewer.calls), (0, 0))
