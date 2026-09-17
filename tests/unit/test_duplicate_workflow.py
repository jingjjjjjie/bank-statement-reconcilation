"""Checks use temporary fixtures only, never customer documents."""
import tempfile
import unittest
import errno
import json
from pathlib import Path
from unittest.mock import patch

from reconciliation import duplicate_workflow as workflow


class WorkflowTests(unittest.TestCase):
    def test_cross_device_move_verifies_before_removing_originals(self):
        """Separate Docker mounts use a verified copy when rename raises EXDEV."""
        rename = Path.rename

        def cross_mount(path, target):
            """Reject only the source-to-review rename, as a mount boundary would."""
            if path.is_relative_to(self.root):
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return rename(path, target)

        with patch.object(Path, "rename", cross_mount):
            files = self.organize_pair()
        self.assertTrue(all(path.read_bytes() == b"same receipt" for path in files))
        self.assertTrue(self.manifest["OrganizationComplete"])
        self.assertFalse(list(files[0].parent.glob(".transfer-*")))

    def test_failed_copy_keeps_original_and_can_resume(self):
        """Corrupt transfer data never removes source files or becomes a final copy."""
        source = self.root / "one.txt"
        source.write_bytes(b"original")
        target = self.base / "copy.txt"
        expected = workflow.fingerprint(source)
        with patch.object(Path, "rename", side_effect=OSError(errno.EXDEV, "cross mount")), \
                patch("reconciliation.duplicate_workflow.shutil.copyfileobj", side_effect=lambda _reader, writer, _size: writer.write(b"bad")):
            with self.assertRaisesRegex(ValueError, "changed during transfer"):
                workflow.move_verified(source, target, expected)
        self.assertEqual(source.read_bytes(), b"original")
        self.assertFalse(target.exists())
        self.assertFalse(list(self.base.glob(".transfer-*")))
        workflow.move_verified(source, target, expected)
        self.assertEqual(target.read_bytes(), b"original")

    def test_resume_partial_manifest_preserves_recorded_locations(self):
        """Recover after one successful move and a failure on the second file."""
        original = workflow.move_verified
        calls = []

        def fail_second(source, target, expected):
            """Leave a real partial organization for the recovery path."""
            calls.append(source)
            if len(calls) == 2:
                raise PermissionError("fixture interruption")
            original(source, target, expected)

        with patch("reconciliation.duplicate_workflow.move_verified", fail_second):
            with self.assertRaises(PermissionError):
                self.organize_pair()
        manifest = json.loads(self.manifest_path.read_text())
        self.assertFalse(manifest["OrganizationComplete"])
        provenance = list(manifest["Files"])
        workflow.finish_organization(self.root, manifest, self.manifest_path)
        self.assertEqual(manifest["Files"], provenance)
        self.assertTrue(manifest["OrganizationComplete"])
        self.assertTrue(all(Path(r["OrganizedPath"]).exists() for r in provenance))
        self.assertTrue(all(not Path(r["OriginalPath"]).exists() for r in provenance))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "supporting"
        self.root.mkdir()
        self.manifest_path = self.base / "manifest.json"

    def organize_pair(self):
        for folder in ("claim-a", "claim-b"):
            location = self.root / folder
            location.mkdir()
            (location / "receipt.txt").write_bytes(b"same receipt")
        self.manifest = workflow.organize(self.root, self.manifest_path)
        return [Path(row["OrganizedPath"]) for row in self.manifest["Files"]]

    def problems(self):
        return workflow.check(self.root, self.manifest, self.manifest_path)

    def test_cleanup_preserves_provenance_and_then_passes(self):
        files = self.organize_pair()
        self.assertEqual(len(files), 2)
        self.assertTrue(all(path.exists() for path in files))
        self.assertTrue(all(not Path(r["OriginalPath"]).exists() for r in self.manifest["Files"]))
        self.assertTrue(self.problems())
        files[0].unlink()
        self.assertEqual(self.problems(), [])
        (self.root / "reintroduced.txt").write_bytes(files[1].read_bytes())
        self.assertTrue(any("exact duplicate" in p for p in self.problems()))

    def test_missing_changed_and_empty_group_block(self):
        files = self.organize_pair()
        files[0].unlink()
        files[1].write_bytes(b"wrong receipt")
        self.assertTrue(any("does not match" in p for p in self.problems()))
        files[1].unlink()
        self.assertTrue(any("0 files" in p for p in self.problems()))
        files[1].parent.rmdir()
        self.assertTrue(any("missing folder" in p for p in self.problems()))

    def test_no_duplicates_pass_and_existing_batch_is_protected(self):
        (self.root / "a.txt").write_bytes(b"unique a")
        (self.root / "b.txt").write_bytes(b"unique b")
        self.manifest = workflow.organize(self.root, self.manifest_path)
        self.assertEqual(self.manifest["Files"], [])
        self.assertEqual(self.problems(), [])
        with self.assertRaises(ValueError):
            workflow.organize(self.root, self.manifest_path)

    def test_unexpected_review_artifacts_are_not_supporting_files(self):
        """Only manifest groups contribute files from the review folder."""
        files = self.organize_pair()
        artifact = self.base / "duplicated" / "benchmark" / "prompt.txt"
        artifact.parent.mkdir()
        artifact.write_text("not a supporting document", encoding="utf-8")
        scanned = workflow.review_files(self.root, self.manifest, self.manifest_path)
        self.assertEqual(set(scanned), set(files))
        self.assertTrue(any("Unexpected group" in p for p in self.problems()))


if __name__ == "__main__":
    unittest.main()
