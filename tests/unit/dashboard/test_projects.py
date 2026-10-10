"""Verify saved project discovery remains read-only and isolates invalid records."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dashboard.services.projects import list_projects
from reconciliation.intake.workspace import SourceSelection


class ProjectTests(unittest.TestCase):
    """Use synthetic folders without extraction or model calls."""

    def test_discovery_preserves_selection_and_reports_missing_folders(self):
        """List multiple projects without activating one or hiding an unavailable input."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = SourceSelection(root, root / "data")
            manifests = []
            for name in ("April", "May"):
                work = root / name
                (work / "documents").mkdir(parents=True)
                (work / "statement").mkdir()
                (work / "statement/bank.pdf").write_bytes(b"fixture")
                sources.save_workspace(work)
                manifests.append(sources.start()[0])
            selection = sources.selection.read_bytes()
            before = {path: path.read_bytes() for path in root.rglob("*.json")}
            projects = list_projects(sources, SimpleNamespace(manifest_path=manifests[0]))
            self.assertEqual({item["name"] for item in projects}, {"April", "May"})
            self.assertEqual(sum(item["active"] for item in projects), 1)
            self.assertTrue(all(item["status"] == "ongoing" for item in projects))
            self.assertEqual(before, {path: path.read_bytes() for path in root.rglob("*.json")})
            (root / "April/documents").rmdir()
            april = next(item for item in list_projects(sources) if item["name"] == "April")
            self.assertEqual(april["status"], "needs_attention")
            self.assertEqual(sources.selection.read_bytes(), selection)

    def test_corrupt_manifest_is_visible_and_empty_list_is_valid(self):
        """Bad saved data cannot hide other projects or break the entire listing."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = SourceSelection(root, root / "data")
            self.assertEqual(list_projects(sources), [])
            folder = root / "duplicated/projects/broken"
            folder.mkdir(parents=True)
            manifest = folder / "duplicate-manifest.json"
            for content in ("{", json.dumps({"SupportingRoot": 5}), "[]"):
                manifest.write_text(content, encoding="utf-8")
                projects = list_projects(sources)
                self.assertEqual(len(projects), 1)
                self.assertEqual(projects[0]["status"], "needs_attention")
                self.assertIsNone(projects[0]["workspace"])
