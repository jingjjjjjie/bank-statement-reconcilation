"""Verify source choices stay read-only until an explicit workflow action."""
import tempfile
import threading
import unittest
import urllib.request
from urllib.parse import urlencode
import json
import os
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from reconciliation.duplicate_workflow import check, fingerprint, organize
from reconciliation.source_selection import SourceSelection
from dashboard.app import handler_for


class SourceSelectionTests(unittest.TestCase):
    def test_workspace_selects_both_inputs_without_moving_files(self):
        """A work folder keeps the statement out of the supporting document scan."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            work = base / "December"
            (work / "documents").mkdir(parents=True)
            (work / "statement").mkdir()
            receipt = work / "documents/receipt.pdf"
            receipt.write_bytes(b"receipt")
            bank = work / "statement/bank.PDF"
            bank.write_bytes(b"statement")
            sources = SourceSelection(base, base / "data")
            result = sources.save_workspace(work)
            self.assertEqual(result["selected"]["files"], 1)
            self.assertEqual(sources.selected(), work / "documents")
            self.assertEqual(sources.selected_bank(), bank)
            self.assertEqual(sources.selected_workspace(), str(work))
            self.assertTrue(receipt.exists())
            self.assertTrue(bank.exists())
            self.assertEqual(sources.preview()["files"], 1)
            (work / "statement/second.pdf").write_bytes(b"another")
            with self.assertRaisesRegex(ValueError, "exactly one"):
                sources.start()

    def test_invalid_workspace_does_not_replace_selection(self):
        """Missing or multiple statements cannot overwrite an existing source choice."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            old = base / "old"
            old.mkdir()
            sources = SourceSelection(base, base / "data")
            sources.save(old)
            work = base / "invalid"
            work.mkdir()
            with self.assertRaisesRegex(ValueError, "documents/ and statement/"):
                sources.save_workspace(work)
            (work / "documents").mkdir()
            (work / "statement").mkdir()
            for count in (0, 2):
                for number in range(count):
                    (work / f"statement/{number}.pdf").write_bytes(b"PDF")
                with self.assertRaisesRegex(ValueError, "exactly one"):
                    sources.save_workspace(work)
                self.assertEqual(sources.selected(), old)

    def test_workspace_http_selection_and_review_navigation(self):
        """Select a work folder through HTTP and keep the home page as its picker."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            work = base / "December"
            (work / "documents").mkdir(parents=True)
            (work / "statement").mkdir()
            (work / "documents/receipt.txt").write_text("receipt")
            (work / "statement/bank.pdf").write_bytes(b"statement")
            sources = SourceSelection(base, base / "data")
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(None, "test-token", sources))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            root = f"http://127.0.0.1:{server.server_port}"

            def post(route, body):
                """Submit a local dashboard action using the fixture session token."""
                request = urllib.request.Request(root + route, json.dumps(body).encode(),
                    {"Content-Type": "application/json", "X-Review-Token": "test-token"})
                with urllib.request.urlopen(request) as response:
                    return json.load(response)

            try:
                result = post("/api/source/workspace-select", {"path": str(work)})
                self.assertEqual(result["workspace"], str(work))
                self.assertEqual(result["selected"]["files"], 1)
                self.assertEqual(result["bank"]["path"], str(work / "statement/bank.pdf"))
                with urllib.request.urlopen(root + "/api/source/preview") as response:
                    preview = json.load(response)
                post("/api/source/start", {"preview": preview["token"]})
                with urllib.request.urlopen(root + "/") as response:
                    page = response.read()
                    self.assertIn(b"Choose your workspace</h1>", page)
                    self.assertIn(b">Proceed</button>", page)
                    self.assertNotIn(b'id="bank-year"', page)
                    self.assertNotIn(b'id="bank-path"', page)
                with urllib.request.urlopen(root + "/bank") as response:
                    page = response.read()
                    self.assertIn(b'id="bank-year"', page)
                    self.assertIn(b'id="prepare-bank"', page)
                with urllib.request.urlopen(root + "/review") as response:
                    self.assertIn(b'/exact-report.js', response.read())
                with urllib.request.urlopen(root + "/api/workspace") as response:
                    self.assertEqual(json.load(response)["name"], "December")
            finally:
                server.shutdown()
                server.server_close()

    def test_reopen_resumes_legacy_interrupted_organization(self):
        """An old partial manifest must finish its moves before becoming active."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            for name in ("a.txt", "b.txt"):
                (source / name).write_bytes(b"same")
            sources = SourceSelection(base, base / "data")
            sources.save(source)
            with patch("reconciliation.duplicate_workflow.move_verified", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    sources.start(sources.preview()["token"])
            path = next((base / "duplicated/projects").glob("*/duplicate-manifest.json"))
            saved = json.loads(path.read_text())
            saved.pop("OrganizationComplete")
            path.write_text(json.dumps(saved), encoding="utf-8")
            manifest, _ = sources.start(sources.preview()["token"])
            completed = json.loads(manifest.read_text())
            self.assertTrue(completed["OrganizationComplete"])
            self.assertTrue(all(Path(r["OrganizedPath"]).is_file() for r in completed["Files"]))
            self.assertEqual(list(source.iterdir()), [])

    def test_browser_roots_are_available_on_current_platform(self):
        """A fresh picker must show drives or POSIX roots without a saved source."""
        with tempfile.TemporaryDirectory() as folder:
            sources = SourceSelection(folder, Path(folder) / "data")
            listing = sources.browse()
            self.assertTrue(listing["folders"])
            if os.name != "nt":
                self.assertIn("/", listing["folders"])
                self.assertIn(str(Path.home()), listing["folders"])

    @unittest.skipIf(os.name == "nt", "Mounted POSIX roots are used inside Docker")
    def test_docker_picker_prioritizes_existing_upload_mounts(self):
        """List mounted uploads first and omit absent mount directories."""
        with tempfile.TemporaryDirectory() as folder:
            sources = SourceSelection(folder, Path(folder) / "data")
            with patch.object(Path, "is_dir", lambda path: str(path) in {"/uploads", "/documents", "/"}):
                self.assertEqual(sources.browse()["folders"], ["/uploads", "/documents", "/"])
            with patch.object(Path, "is_dir", lambda path: str(path) == "/"):
                self.assertEqual(sources.browse()["folders"], ["/"])

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

            with patch("reconciliation.bank_statement.extract", return_value={}), patch("reconciliation.bank_statement.write_master", side_effect=write_fixture):
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
                    self.assertEqual(response.url, root)
                    self.assertIn(b"Workspace selection", response.read())
                with urllib.request.urlopen(root + "/api/source") as response:
                    self.assertIsNone(json.load(response)["active"])
                for route in ("/documents", "/documents/", "/documents.js", "/documents.css"):
                    with urllib.request.urlopen(root + route) as response:
                        self.assertEqual(response.url, root + route)
                        self.assertEqual(response.status, 200)
                with urllib.request.urlopen(root + "/api/document-status") as response:
                    self.assertEqual(json.load(response), {"prepared": False, "documents": []})
                query = urlencode({"path": str(base), "kind": "bank"})
                with urllib.request.urlopen(root + "/api/source/browse?" + query) as response:
                    self.assertEqual(json.load(response)["path"], str(base))
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
