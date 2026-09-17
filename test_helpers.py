"""Shared offline fixtures for workflow regression tests."""
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def mock_codex(fake_run):
    """Intercept login and managed processes so tests never start a real CLI."""
    class Process:
        """Expose the process lifecycle used by the reviewer."""

        def __init__(self, command, **kwargs):
            """Remember the command and streams until communication begins."""
            self.command = command
            self.kwargs = kwargs
            self.returncode = None

        def communicate(self, input=None, timeout=None):
            """Simulate output or timeout, allowing cleanup after a killed call."""
            if self.returncode is None:
                result = fake_run(self.command, input=input, timeout=timeout, **self.kwargs)
                self.returncode = result.returncode
            return None, None

        def poll(self):
            """Report whether the simulated process is still running."""
            return self.returncode

        def kill(self):
            """Mark the process stopped before timeout cleanup."""
            self.returncode = -1

        terminate = kill

    with patch("codex_reviewer.subprocess.run", side_effect=fake_run), \
            patch("codex_reviewer.subprocess.Popen", Process):
        yield
