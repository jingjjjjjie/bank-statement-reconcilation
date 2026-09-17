"""Run cancellable process trees with bounded cleanup and verified exits."""
import os
import signal
import subprocess
import threading
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryFile
from time import monotonic, sleep


class ReviewCancelled(Exception):
    """A stopped review must not accept an interrupted model response."""


class ProcessStopError(RuntimeError):
    """Process-tree shutdown could not be verified; restarting is unsafe."""


class PosixProcess:
    """Own a separate process group without preexec_fn in worker threads."""

    def __init__(self, command, stdin, stdout, stderr, cwd=None):
        """Start a session so cancellation never signals the dashboard's group."""
        self.process = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr,
                                        cwd=cwd, start_new_session=True)
        self.pid = self.process.pid

    def poll(self):
        """Reap the direct child and return its exit status."""
        return self.process.poll()

    def alive(self):
        """Check live group members; Linux zombies have already stopped running."""
        self.poll()
        if Path("/proc").is_dir():
            for path in Path("/proc").glob("[0-9]*/stat"):
                try:
                    fields = path.read_text().rsplit(")", 1)[1].split()
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if int(fields[2]) == self.pid and fields[0] not in ("Z", "X"):
                    return True
            return False
        try:
            os.killpg(self.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def terminate(self, force=False):
        """Signal the whole group, escalating to SIGKILL when requested."""
        try:
            os.killpg(self.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass

    def close(self):
        """Reap the direct child after verified shutdown."""
        self.process.wait(timeout=0)


def spawn(command, **streams):
    """Select the operating system's process-tree implementation."""
    if os.name == "nt":
        from reconciliation.windows_process import WindowsProcess
        return WindowsProcess(command, **streams)
    return PosixProcess(command, **streams)


class ProcessManager:
    """Share cancellation and process ownership across all review workers."""

    def __init__(self, cancel_event=None, grace=1.0, kill_timeout=5.0):
        """Keep launch registration and cancellation under one lock."""
        self.cancelled = cancel_event if cancel_event is not None else threading.Event()
        self.grace, self.kill_timeout = grace, kill_timeout
        self._lock = threading.Lock()
        self._active = set()

    @property
    def active_count(self):
        """Count process trees whose cleanup has not yet been verified."""
        with self._lock:
            return len(self._active)

    def cancel(self):
        """Block launches and wake every owner to stop its tree concurrently."""
        with self._lock:
            self.cancelled.set()

    def _wait_empty(self, process, timeout):
        """Wait a bounded interval for the main process and its tree to exit."""
        deadline = monotonic() + timeout
        while True:
            if process.poll() is not None and not process.alive():
                return True
            if monotonic() >= deadline:
                return False
            sleep(0.02)

    def _cleanup(self, process):
        """Terminate leftovers, escalate, and retain unverified trees on failure."""
        try:
            if not self._wait_empty(process, 0):
                process.terminate()
                if not self._wait_empty(process, self.grace):
                    process.terminate(force=True)
                    if not self._wait_empty(process, self.kill_timeout):
                        raise TimeoutError("process tree is still active")
            process.close()
        except Exception as error:
            raise ProcessStopError(f"Cannot verify shutdown of process {process.pid}: {error}") from error
        with self._lock:
            self._active.remove(process)

    def run(self, command, *, input="", timeout=240, stdout=None, stderr=None, cwd=None, audit=None):
        """Run with file-backed I/O so unread pipes cannot delay cancellation."""
        audit = audit if audit is not None else {}
        with ExitStack() as stack:
            stdin = stack.enter_context(TemporaryFile())
            stdin.write(input.encode("utf-8"))
            stdin.seek(0)
            output = stdout if stdout is not None else stack.enter_context(TemporaryFile())
            errors = stderr if stderr is not None else stack.enter_context(TemporaryFile())
            with self._lock:
                if self.cancelled.is_set():
                    raise ReviewCancelled("Review stopped by user")
                process = spawn(command, stdin=stdin, stdout=output, stderr=errors, cwd=cwd)
                self._active.add(process)
                audit.update(pid=process.pid, exit_verified=False)
            try:
                deadline = monotonic() + timeout
                while process.poll() is None:
                    if self.cancelled.wait(0.05):
                        raise ReviewCancelled("Review stopped by user")
                    if monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(command, timeout)
                if self.cancelled.is_set():
                    raise ReviewCancelled("Review stopped by user")
            finally:
                try:
                    self._cleanup(process)
                    audit["exit_verified"] = True
                finally:
                    try:
                        audit["returncode"] = process.poll()
                    except OSError:
                        audit["returncode"] = None
            if self.cancelled.is_set():
                raise ReviewCancelled("Review stopped by user")
            captured = []
            for supplied, stream in ((stdout, output), (stderr, errors)):
                if supplied is None:
                    stream.seek(0)
                    captured.append(stream.read().decode("utf-8", errors="replace"))
                else:
                    captured.append(None)
            return subprocess.CompletedProcess(command, audit["returncode"], *captured)
