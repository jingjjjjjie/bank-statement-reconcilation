"""Keep retired content-review links usable without changing historical evidence."""

import json
import tempfile
import threading
import unittest
from tests.http_server import TestServer
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright, expect

from dashboard.app import Review, create_app
from tests.unit.test_content_review import FixtureReviewer
from reconciliation.duplicate_workflow import organize
from reconciliation.vision_workflow import load, prepare, run


class ContentBrowserTests(unittest.TestCase):
    def test_retired_page_redirects_without_losing_evidence(self):
        """Redirect the retired page and preserve saved comparison history."""
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
            server = TestServer(("127.0.0.1", 0), create_app(review, "browser-token"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_port}/content-review")
                    expect(page).to_have_url(f"http://127.0.0.1:{server.server_port}/documents")
                    expect(page.locator("h1")).to_have_text("Documents")
                    expect(page.locator('.rail a[href="/content-review"]')).to_have_count(0)
                    self.assertEqual(load(work)[1]["pairs"], state["pairs"])
                    self.assertFalse(errors)
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
