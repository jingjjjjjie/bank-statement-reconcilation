"""Verify source choices stay read-only until an explicit workflow action."""
import base64
import tempfile
import threading
import unittest
import urllib.request
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from duplicate_workflow import fingerprint
from source_selection import SourceSelection, choose_bank_pdf, choose_folder
from dashboard.app import handler_for


class SourceSelectionTests(unittest.TestCase):
    def test_native_pickers_do_not_require_tkinter(self):
        """Decode Windows picker paths and preserve cancelled selections."""
        path = r"C:\Users\Example\桌面\Documents"
        encoded = base64.b64encode(path.encode("utf-16-le")).decode("ascii")
        with patch("source_selection.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = encoded + "\n"
            self.assertEqual(choose_folder(), path)
            self.assertIn("FolderBrowserDialog", run.call_args.args[0][-1])
            self.assertNotIn("Hidden", run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs["timeout"], 120)
            run.return_value.stdout = ""
            self.assertEqual(choose_bank_pdf(), "")
            self.assertIn("OpenFileDialog", run.call_args.args[0][-1])

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
            self.assertEqual(sources.save(documents)["files"], 2)
            self.assertEqual(sources.save_bank(pdf)["path"], str(pdf.resolve()))
            self.assertTrue((documents / "a.txt").exists())
            manifest, _ = sources.start()
            self.assertTrue(manifest.is_file())
            self.assertFalse((documents / "a.txt").exists())
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

    def test_dashboard_opens_picker_without_an_existing_manifest(self):
        """A fresh workspace reaches source setup before a review exists."""
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
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
