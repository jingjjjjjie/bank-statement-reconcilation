"""Browser smoke test for settings and keep/undo using temporary fixtures."""
import tempfile
import threading
from tests.http_server import TestServer
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright, expect
from dashboard.app import Review, create_app
from reconciliation.duplicate_workflow import organize
from reconciliation.review_settings import DEFAULTS
from reconciliation import development_cache


def main():
    # Use installed Chrome, avoiding a separate browser download.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1080}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # Exercise actual browser keep/undo actions against isolated fixture documents.
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            isolated_mode = patch.object(development_cache, "WORKSPACE", base)
            isolated_mode.start()
            development_cache.set_mode(True)
            root = base / "sources"
            root.mkdir()
            image = Image.new("RGB", (400, 250), "white")
            ImageDraw.Draw(image).text((20, 20), "Test receipt\nMYR 62.50", fill="black", font_size=24)
            image.save(root / "copy-a.png")
            (root / "copy-b.png").write_bytes((root / "copy-a.png").read_bytes())
            manifest = base / "manifest.json"
            organize(root, manifest)
            review = Review(manifest, base / "data")
            server = TestServer(("127.0.0.1", 0), create_app(review, "browser-test-token"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                page.set_viewport_size({"width": 1440, "height": 1080})
                page.goto(f"http://127.0.0.1:{server.server_port}/review")
                # Save settings only in the fixture workspace and verify they survive reload.
                page.locator('.rail').get_by_role("link", name="Settings", exact=True).click()
                expect(page).to_have_url(f"http://127.0.0.1:{server.server_port}/settings")
                expect(page.locator("#settings-fields")).to_be_enabled()
                page.locator("#pdf-mode").select_option("auto")
                page.locator("#pictures-enabled").uncheck()
                page.locator("#codex-enabled").uncheck()
                page.locator("#max-calls").fill("7")
                expect(page.locator("#call-example")).to_contain_text("pause before request 8")
                page.locator("#pdf-model").select_option("gpt-5.6-terra")
                page.locator("#pdf-reasoning").select_option("high")
                page.locator("#images-model").select_option("gpt-5.6-sol")
                page.locator("#images-reasoning").select_option("low")
                page.get_by_role("button", name="Save settings").click()
                expect(page.locator("#toast")).to_contain_text("Settings saved")
                page.reload()
                expect(page.locator("#settings-fields")).to_be_enabled()
                expect(page.locator("#pdf-mode")).to_have_value("auto")
                expect(page.locator("#pictures-enabled")).not_to_be_checked()
                expect(page.locator("#codex-enabled")).not_to_be_checked()
                expect(page.locator("#max-calls")).to_have_value("7")
                expect(page.locator("#pdf-model")).to_have_value("gpt-5.6-terra")
                expect(page.locator("#pdf-reasoning")).to_have_value("high")
                expect(page.locator("#images-model")).to_have_value("gpt-5.6-sol")
                expect(page.locator("#images-reasoning")).to_have_value("low")
                expect(page.locator("#comparison-model")).to_have_count(0)
                expect(page.locator("#excel-model")).to_have_value(DEFAULTS["model"])
                # Check explicit explanations, saved-state tracking and mobile layout.
                expect(page.locator("#call-definition")).to_contain_text("failed or timed-out")
                expect(page.locator("#call-definition")).to_contain_text("cached results")
                expect(page.locator("#save-settings")).to_be_disabled()
                page.locator("#max-calls").fill("10")
                expect(page.locator("#save-state")).to_have_text("Unsaved changes")
                page.get_by_role("button", name="Discard changes").click()
                expect(page.locator("#max-calls")).to_have_value("7")
                page.get_by_role("button", name="Use testing defaults").click()
                expect(page.locator("#pdf-mode")).to_have_value(DEFAULTS["pdf_mode"])
                expect(page.locator("#max-calls")).to_have_value(str(DEFAULTS["max_calls"]))
                expect(page.locator("#save-state")).to_have_text("Unsaved changes")
                page.get_by_role("button", name="Discard changes").click()
                expect(page.locator("#max-calls")).to_have_value("7")
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.get_by_role("link", name="Back to review").click()
                expect(page.locator("#settings-form")).to_have_count(0)
                page.set_viewport_size({"width": 1440, "height": 1080})
                page.get_by_role("button", name="Retain this file", exact=True).first.click()
                expect(page.locator("#group-status")).to_have_text("Complete")
                assert page.locator(".file-card.kept").count() == 1
                assert page.locator(".file-card.archived").count() == 1
                page.reload()
                page.get_by_role("button", name="Undo selection").click()
                expect(page.locator("#group-status")).to_have_text("Pending")
                assert page.locator(".file-card.archived").count() == 0
            finally:
                server.shutdown()
                server.server_close()
                isolated_mode.stop()
        browser.close()
        assert not errors, errors
        print("PASS: real previews, validation, mobile layout, fixture keep/undo and reload persistence.")


if __name__ == "__main__":
    main()
