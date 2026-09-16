"""Verify source choices stay read-only until an explicit workflow action."""
import tempfile
import threading
import unittest
import urllib.request
from urllib.parse import urlencode
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from duplicate_workflow import check, fingerprint, organize
from source_selection import SourceSelection
from dashboard.app import handler_for


class SourceSelectionTests(unittest.TestCase):
    def test_preview_counts_moves_and_blocks_changed_source(self):
        """Require a fresh move preview before creating a review."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / "documents"
            source.mkdir()
            (source / "a.txt").write_text("same", encoding="utf-8")
            (source / "b.txt").write_text("same", encoding="utf-8")
            selected = SourceSelection(base, base / "dashboard-data")
            selected.save(source)
            preview = selected.preview()
            self.assertEqual((preview["files"], preview["groups"], preview["copies_to_move"]), (2, 1, 2))
            (source / "new.txt").write_text("new", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed since the preview"):
                selected.start(preview["token"])
            self.assertTrue((source / "a.txt").exists())

    def test_in_page_browser_lists_folders_and_pdfs(self):
        """Browse one directory without opening a desktop dialog or moving files."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / "receipts").mkdir()
            (base / "statement.pdf").write_bytes(b"fixture")
            (base / "other.txt").write_text("fixture", encoding="utf-8")
            sources = SourceSelection(base, base / "dashboard-data")
            listing = sources.browse(base, pdfs=True)
            self.assertIn(str(base / "receipts"), listing["folders"])
            self.assertEqual(listing["files"], [str(base / "statement.pdf")])
            self.assertEqual(sources.browse(base)["files"], [])

    def test_separate_sources_and_bank_master_protection(self):
        """Keep folder and PDF choices separate and preserve an existing bank master."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            documents = base / "documents"
            documents.mkdir()
            (documents / "a.txt").write_text("same", encoding="utf-8")
            (documents / "b.txt").write_text("same", encoding="utf-8")
            pdf = base / "statement.pdf"
            pdf.write_bytes(b"%PDF-1.4\nfixture")
            sources = SourceSelection(base, base / "dashboard-data")
            legacy = base / "legacy"
            legacy.mkdir()
            (legacy / "one.txt").write_text("old", encoding="utf-8")
            (legacy / "two.txt").write_text("old", encoding="utf-8")
            legacy_manifest = base / "legacy-manifest.json"
            old_review = organize(legacy, legacy_manifest)
            self.assertEqual(sources.save(documents)["files"], 2)
            self.assertEqual(sources.save_bank(pdf)["path"], str(pdf.resolve()))
            self.assertTrue((documents / "a.txt").exists())
            manifest, _ = sources.start()
            self.assertTrue(manifest.is_file())
            self.assertFalse((documents / "a.txt").exists())
            self.assertFalse(any("Unexpected group: projects" in item for item in
                                 check(legacy, old_review, legacy_manifest)))
            sources.activate(manifest)
            self.assertEqual(sources.active_manifest(base / "unused.json"), manifest)

            digest = fingerprint(pdf).lower()

            def write_fixture(_result, path):
                """Write a small master with the selected source identity."""
                path.write_text(f"source_sha256,year_supplied\n{digest},2025\n", encoding="utf-8")

            with patch("bank_statement.extract", return_value={}), patch("bank_statement.write_master", side_effect=write_fixture):
                self.assertFalse(sources.prepare_bank(manifest, 2025)["existing"])
                self.assertTrue(sources.prepare_bank(manifest, 2025)["existing"])
                with self.assertRaisesRegex(ValueError, "not replaced"):
                    sources.prepare_bank(manifest, 2026)

    def test_rejects_workspace_root_and_non_pdf(self):
        """Avoid scanning review output and accepting unsupported bank inputs."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            sources = SourceSelection(base, base / "dashboard-data")
            with self.assertRaises(ValueError):
                sources.save(base)
            text_file = base / "statement.txt"
            text_file.write_text("not a PDF", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PDF"):
                sources.save_bank(text_file)

    def test_dashboard_browses_without_an_existing_manifest(self):
        """A fresh workspace can list folders before a review exists."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            sources = SourceSelection(base, base / "dashboard-data")
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(None, "test-token", sources))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(root) as response:
                    self.assertEqual(response.url, root + "/source")
                with urllib.request.urlopen(root + "/api/source") as response:
                    self.assertIsNone(json.load(response)["active"])
                query = urlencode({"path": str(base), "kind": "bank"})
                with urllib.request.urlopen(root + "/api/source/browse?" + query) as response:
                    self.assertEqual(json.load(response)["path"], str(base))
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
