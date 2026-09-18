"""Check the document status page against saved review checkpoints."""
import json
import tempfile
import threading
import unittest
from tests.http_server import TestServer
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from dashboard.app import Review, create_app
from dashboard.document_status import snapshot
from tests.unit.test_content_review import FixtureReviewer
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
            self.assertTrue(all(item["status"] == "Queued" for item in waiting))
            server = TestServer(("127.0.0.1", 0), create_app(review, "test-token"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
                    page = browser.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_port}/documents")
                    expect(page.locator("#document-rows tr")).to_have_count(2)
                    expect(page.locator("#document-rows .document-status").first).to_have_text("Queued")
                    index, state = load(work)
                    run(work, index, state, FixtureReviewer(), extraction_only=True)
                    page.reload()
                    expect(page.locator("#document-rows .document-status").first).to_have_text("Needs review")
                    page.screenshot(path=".tools/documents-desktop.png", full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                    page.screenshot(path=".tools/documents-mobile.png", full_page=True)
                    page.locator("#document-search").fill("first.png")
                    expect(page.locator("#document-rows tr")).to_have_count(1)
                    for filename in ("first.png", "second.png"):
                        page.locator("#document-search").fill(filename)
                        page.locator("#document-rows").get_by_role("link", name="Review results", exact=True).click()
                        digest = next(key for key, document in index["documents"].items()
                                      if Path(document["paths"][0]).name == filename)
                        expect(page.locator("#receipt-unit")).to_have_value(digest + ":0")
                        page.get_by_role("link", name="Back to document status").click()
                    self.assertFalse(errors)
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
