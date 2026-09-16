"""Browser smoke test for the pass-two admin review page."""

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright, expect

from dashboard.app import Review, handler_for
from dashboard.test_content_review import FixtureReviewer
from duplicate_workflow import organize
from vision_workflow import load, prepare, run


class ContentBrowserTests(unittest.TestCase):
    def test_candidate_can_be_reviewed_in_browser(self):
        """Render original previews and save a named keep-both verdict."""
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if not chrome.is_file():
            self.skipTest("Installed Chrome is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "sources"
            root.mkdir()
            Image.new("RGB", (40, 40), "white").save(root / "left.png")
            Image.new("RGB", (40, 40), "black").save(root / "right.png")
            manifest = base / "manifest.json"
            organize(root, manifest)
            config = base / "review_config.json"
            config.write_text(json.dumps({"pdf_mode": "auto", "pictures_enabled": True,
                "codex_enabled": True, "max_calls": 20, "model": "", "reasoning": "default", "stages": {}}), encoding="utf-8")
            work = base / "review"
            prepare(manifest, work, config)
            index, state = load(work)
            run(work, index, state, FixtureReviewer())
            review = Review(manifest, base / "data")
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(review, "browser-token"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_port}/content-review")
                    expect(page.locator(".content-pair")).to_have_count(1)
                    expect(page.locator(".content-preview").first).to_have_js_property("complete", True)
                    page.locator("#admin-name").fill("Admin")
                    page.locator(".content-pair textarea").fill("Separate records")
                    page.get_by_role("button", name="Keep both").click()
                    expect(page.locator(".content-decision")).to_contain_text("Admin decision: keep_both by Admin")
                    expect(page.locator(".content-decision-bar button")).to_have_text("Undo decision")
                    page.get_by_role("button", name="Undo decision").click()
                    expect(page.locator(".content-decision")).to_contain_text("Admin decision pending")
                    self.assertFalse(errors)
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
