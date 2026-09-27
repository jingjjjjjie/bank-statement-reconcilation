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


class FakeReviewer:
    """Offline model client: returns one fixed, schema-valid extraction for any request.

    Subclass and override `ask` to record calls or simulate failures.
    """
    model = "fixture"

    def ask(self, prompt, schema, images=()):
        """Return a deterministic legacy-shaped extraction; tests check orchestration, not accuracy."""
        return {"receipts": [], "readable": True, "supporting_evidence_status": "potential_support",
                "supporting_evidence_reason": "Visible transaction details", "document_type": "receipt",
                "receipt_status": "receipt", "invoice_numbers": ["TEST-1"], "company": [],
                "brief_description": "fixture", "references": ["TEST-1"], "parties": [], "dates": [],
                "amounts_and_currencies": ["MYR 1"], "money": [{"amount": "1.00", "currency": "MYR", "role": "grand_total"}],
                "details": "fixture", "annotations_and_signatures": "none", "limitations": []}


class ReviewFolder:
    """A temporary supporting folder with two images, its manifest path and a review folder.

    `ReviewFolder(test.addCleanup)` works inside any test; `prepared()` organizes exact
    duplicates, prepares the review and returns `(index, state)`.
    """

    def __init__(self, add_cleanup):
        """Create sources outside any customer folder; removed when the test finishes."""
        import tempfile
        from pathlib import Path
        from PIL import Image
        temp = tempfile.TemporaryDirectory()
        add_cleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "sources"
        self.root.mkdir()
        self.work = self.base / "review"
        self.manifest = self.base / "manifest.json"
        for name, color in (("a.png", "white"), ("b.png", "gray")):
            Image.new("RGB", (80, 80), color).save(self.root / name)

    def prepared(self, duplicate=False):
        """Organize exact copies, prepare the review and return `(index, state)`."""
        from reconciliation import vision_workflow
        from reconciliation.duplicate_workflow import organize
        if duplicate:
            (self.root / "copy.png").write_bytes((self.root / "a.png").read_bytes())
        organize(self.root, self.manifest)
        vision_workflow.prepare(self.manifest, self.work)
        return vision_workflow.load(self.work)


class ReviewFixture:
    """TestCase mixin exposing a fresh `ReviewFolder` as `self.base`, `self.root`, `self.work`, `self.manifest`."""

    def setUp(self):
        """Create the folder for this test."""
        self.folder = ReviewFolder(self.addCleanup)
        self.base, self.root, self.work, self.manifest = (
            self.folder.base, self.folder.root, self.folder.work, self.folder.manifest)

    def prepared(self, duplicate=False):
        """Prepare the review; see `ReviewFolder.prepared`."""
        return self.folder.prepared(duplicate)
