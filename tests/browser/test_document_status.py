"""Check the document status page against saved review checkpoints."""
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from dashboard.app import Review, handler_for
from dashboard.document_status import snapshot
from dashboard.test_content_review import FixtureReviewer
from reconciliation.duplicate_workflow import organize
from reconciliation.vision_workflow import load, prepare, run


class DocumentStatusTests(unittest.TestCase):
    def test_every_document_has_a_saved_stage(self):
        """Show pending extraction, then admin review after model fixtures finish."""
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if not chrome.is_file():
            self.skipTest("Installed Chrome is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "sources"
            source.mkdir()
            Image.new("RGB", (20, 20), "white").save(source / "first.png")
            Image.new("RGB", (20, 20), "black").save(source / "second.png")
            manifest = base / "manifest.json"
            organize(source, manifest)
            (base / "review_config.json").write_text(json.dumps({"pdf_mode": "auto", "pictures_enabled": True,
                "codex_enabled": True, "max_calls": 20, "model": "", "reasoning": "default", "stages": {}}), encoding="utf-8")
            review = Review(manifest, base / "data")
            work = base / "review"
            prepare(manifest, work, review.config_path)
            waiting = snapshot(review)["documents"]
            self.assertEqual(len(waiting), 2)
            self.assertTrue(all(item["status"] == "Waiting for extraction" for item in waiting))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(review, "test-token"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
                    page = browser.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_port}/documents")
                    expect(page.locator("#document-rows tr")).to_have_count(2)
                    expect(page.locator("#document-rows .document-status").first).to_have_text("Waiting for extraction")
                    index, state = load(work)
                    run(work, index, state, FixtureReviewer())
                    page.reload()
                    expect(page.locator("#document-rows .document-status").first).to_have_text("Admin review")
                    page.locator("#document-search").fill("first.png")
                    expect(page.locator("#document-rows tr")).to_have_count(1)
                    self.assertFalse(errors)
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
