"""Verify automatic duplicate reports preserve sources and unblock content review."""
import json
import tempfile
import unittest
from pathlib import Path

from dashboard.review import Review
from reconciliation.duplicate_workflow import check, organize
from reconciliation.exact_report import prepare
from reconciliation.source_selection import SourceSelection
from reconciliation.vision_workflow import inventory


class ExactReportTests(unittest.TestCase):
    def setUp(self):
        """Create a work folder with renamed copies and a different same-size file."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.work = self.base / "work"
        self.root = self.work / "documents"
        self.root.mkdir(parents=True)
        (self.work / "statement").mkdir()
        (self.work / "statement/bank.pdf").write_bytes(b"statement")
        for name, data in (("one.txt", b"same"), ("renamed.txt", b"same"), ("other.txt", b"diff")):
            (self.root / name).write_bytes(data)
        self.project = self.base / "project"
        self.project.mkdir()
        self.manifest = self.project / "duplicate-manifest.json"

    def test_report_groups_all_copies_and_deduplicates_model_inputs(self):
        """Report exact copies without manual decisions or changing original bytes."""
        manifest = prepare(self.root, self.manifest)
        self.assertEqual(manifest["Summary"], {"files": 3, "groups": 1, "copies": 2,
                                               "extra_copies": 1, "unique_documents": 2})
        self.assertEqual(len(list((self.work / "output/duplicates/group-001").iterdir())), 2)
        self.assertEqual(len(list(self.root.iterdir())), 3)
        self.assertEqual(check(self.root, manifest, self.manifest), [])
        self.assertEqual(len(inventory(self.root, self.manifest)), 2)
        review = Review(self.manifest, self.project / "dashboard-data")
        self.assertEqual(review.snapshot()["pending"], 0)
        with self.assertRaisesRegex(ValueError, "no selection"):
            review.keep("group-001", review.groups["group-001"][0])
        self.assertEqual(prepare(self.root, self.manifest), manifest)
        (self.root / "one.txt").write_bytes(b"edit")
        self.assertTrue(check(self.root, manifest, self.manifest))
        with self.assertRaisesRegex(ValueError, "Sources changed"):
            prepare(self.root, self.manifest)

    def test_legacy_migration_restores_copies_without_deleting_recovery(self):
        """Copy back archived originals while retaining old organization and decisions."""
        old = organize(self.root, self.manifest)
        review = Review(self.manifest, self.project / "dashboard-data")
        review.keep("group-001", review.groups["group-001"][0])
        recovery = list((review.data / "recovery").rglob("*.txt"))
        result = prepare(self.root, self.manifest)
        self.assertEqual(result["Summary"]["copies"], 2)
        self.assertEqual(len(list(self.root.iterdir())), 3)
        self.assertTrue(all(path.is_file() for path in recovery))
        self.assertEqual(json.loads((self.project / "legacy-duplicate-manifest.json").read_text())["Files"], old["Files"])

    def test_workspace_start_uses_report_and_preserves_statement(self):
        """The workspace entry point creates the automatic report on Proceed."""
        sources = SourceSelection(self.base, self.base / "data")
        sources.save(self.root)
        manifest, _ = sources.start(sources.preview()["token"])
        self.assertEqual(json.loads(manifest.read_text())["Mode"], "exact_report")
        self.assertEqual((self.work / "statement/bank.pdf").read_bytes(), b"statement")

    def test_existing_unmanaged_output_is_not_overwritten(self):
        """An existing output folder without our report must remain untouched."""
        folder = self.work / "output/duplicates"
        folder.mkdir(parents=True)
        (folder / "keep.txt").write_text("keep")
        with self.assertRaisesRegex(ValueError, "already exists"):
            prepare(self.root, self.manifest)
        self.assertEqual((folder / "keep.txt").read_text(), "keep")
