"""Shared offline fixtures for workflow regression tests."""
from contextlib import contextmanager
from unittest.mock import patch
from reconciliation.process_manager import ReviewCancelled


@contextmanager
def mock_codex(fake_run):
    """Intercept login and managed processes so tests never start a real CLI."""
    def run(manager, command, **kwargs):
        """Mock the process boundary; real containment has separate OS tests."""
        if manager.cancelled.is_set():
            raise ReviewCancelled("Review stopped by user")
        audit = kwargs.pop("audit", {})
        result = fake_run(command, **kwargs)
        audit.update(pid=123, returncode=result.returncode, exit_verified=True)
        return result

    with patch("reconciliation.process_manager.ProcessManager.run", run):
        yield
