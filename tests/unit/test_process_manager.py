"""Exercise real process trees without Codex calls or customer documents."""
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch

from reconciliation.process_manager import ProcessManager, ProcessStopError, ReviewCancelled, spawn


CHILD = "import time; time.sleep(60)"
TREE = """import pathlib, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', sys.argv[2]])
pathlib.Path(sys.argv[1]).write_text(str(child.pid))
time.sleep(60)
"""


def alive(pid):
    """Check actual process exit using an OS handle or Linux process state."""
    if os.name == "nt":
        from reconciliation.windows_process import api, close_handle, wait, W
        open_process = api("OpenProcess", W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
        handle = open_process(0x100000, False, pid)
        if not handle:
            return False
        try:
            return wait(handle, 0) == 258
        finally:
            close_handle(handle)
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
    except FileNotFoundError:
        return False


class ProcessManagerTests(unittest.TestCase):
    def setUp(self):
        """Keep all synthetic process artifacts in a temporary directory."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.manager = ProcessManager(grace=0.15, kill_timeout=3)
        self.addCleanup(self.manager.cancel)

    def wait_file(self, path):
        """Wait for a child readiness marker without relying on launch timing."""
        deadline = monotonic() + 5
        while monotonic() < deadline:
            if path.exists() and path.read_text():
                return int(path.read_text())
            sleep(0.01)
        self.fail(f"Child did not become ready: {path}")

    def test_normal_input_output_and_nonzero_exit(self):
        """Preserve Unicode input, argument quoting, output, and exit status."""
        audit = {}
        code = "import sys; print(sys.stdin.read()); print(sys.argv[1], file=sys.stderr); sys.exit(7)"
        result = self.manager.run([sys.executable, "-X", "utf8", "-c", code, 'space and "quote"'],
                                  input="receipt \u4e16\u754c", audit=audit)
        self.assertEqual(result.returncode, 7)
        self.assertIn("receipt \u4e16\u754c", result.stdout)
        self.assertIn('space and "quote"', result.stderr)
        self.assertTrue(audit["exit_verified"])
        self.assertEqual(self.manager.active_count, 0)

    def test_cancel_parallel_trees_and_preserve_unrelated_process(self):
        """Stop four parents and their children without touching another process."""
        unrelated = subprocess.Popen([sys.executable, "-c", CHILD])
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                audits = [{} for _ in range(4)]
                markers = [self.folder / f"child-{n}" for n in range(4)]
                futures = [pool.submit(self.manager.run, [sys.executable, "-c", TREE, str(path), CHILD],
                                       input="x" * 1000000, audit=audit)
                           for path, audit in zip(markers, audits)]
                try:
                    children = [self.wait_file(path) for path in markers]
                    self.assertEqual(self.manager.active_count, 4)
                finally:
                    self.manager.cancel()
                for future in futures:
                    with self.assertRaises(ReviewCancelled):
                        future.result(timeout=5)
            self.assertTrue(all(audit["exit_verified"] for audit in audits))
            self.assertTrue(all(not alive(pid) for pid in children + [a["pid"] for a in audits]))
            self.assertIsNone(unrelated.poll())
            self.assertEqual(self.manager.active_count, 0)
            with self.assertRaises(ReviewCancelled):
                self.manager.run([sys.executable, "-c", "raise Exception('must not run')"])
        finally:
            unrelated.kill()
            unrelated.wait(timeout=5)

    def test_timeout_cleans_child_and_parent(self):
        """Timeout follows the same verified process-tree cleanup as Stop."""
        marker, audit = self.folder / "child", {}
        with self.assertRaises(subprocess.TimeoutExpired):
            self.manager.run([sys.executable, "-c", TREE, str(marker), CHILD], timeout=1.5, audit=audit)
        self.assertFalse(alive(self.wait_file(marker)))
        self.assertFalse(alive(audit["pid"]))
        self.assertTrue(audit["exit_verified"])

    def test_parent_exit_does_not_leave_child_running(self):
        """A successful main-process exit must also clean up remaining children."""
        marker = self.folder / "child"
        code = TREE.replace("time.sleep(60)", "")
        result = self.manager.run([sys.executable, "-c", code, str(marker), CHILD])
        self.assertEqual(result.returncode, 0)
        self.assertFalse(alive(self.wait_file(marker)))
        self.assertEqual(self.manager.active_count, 0)

    def test_stop_during_launch_cannot_miss_registration(self):
        """Cancellation racing with native creation still owns the new process."""
        launched, release = threading.Event(), threading.Event()
        audit = {}

        def paused_spawn(*args, **kwargs):
            """Hold the launch lock after creating a real contained process."""
            process = spawn(*args, **kwargs)
            launched.set()
            release.wait(timeout=3)
            return process

        with patch("reconciliation.process_manager.spawn", paused_spawn), ThreadPoolExecutor(2) as pool:
            future = pool.submit(self.manager.run, [sys.executable, "-c", CHILD], audit=audit)
            self.assertTrue(launched.wait(timeout=3))
            stop = pool.submit(self.manager.cancel)
            release.set()
            stop.result(timeout=3)
            with self.assertRaises(ReviewCancelled):
                future.result(timeout=5)
        self.assertTrue(audit["exit_verified"])
        self.assertFalse(alive(audit["pid"]))

    def test_failed_verification_remains_tracked(self):
        """Never report zero active processes when termination cannot be verified."""
        class RefusesToStop:
            """Represent an operating-system termination failure."""
            pid = 123

            def poll(self):
                """Keep the process active."""
                return None

            def terminate(self, force=False):
                """Simulate an explicit OS failure."""
                raise PermissionError("fixture denial")

        audit = {}
        with patch("reconciliation.process_manager.spawn", return_value=RefusesToStop()):
            with self.assertRaises(ProcessStopError):
                self.manager.run(["fixture"], timeout=0, audit=audit)
        self.assertEqual(self.manager.active_count, 1)
        self.assertFalse(audit["exit_verified"])

    @unittest.skipIf(os.name == "nt", "SIGTERM escalation is POSIX-specific")
    def test_sigterm_ignoring_tree_is_force_killed(self):
        """Escalate to SIGKILL when both parent and child ignore graceful stop."""
        marker, audit = self.folder / "child", {}
        ignore = "import signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        with self.assertRaises(subprocess.TimeoutExpired):
            self.manager.run([sys.executable, "-c", ignore + TREE, str(marker), ignore + CHILD],
                             timeout=1.5, audit=audit)
        self.assertTrue(audit["exit_verified"])
        self.assertFalse(alive(self.wait_file(marker)))
