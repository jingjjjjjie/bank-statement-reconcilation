"""Exercise the receipt split and combined match flow in Chromium with fixture data."""
import threading
import unittest
import json
from pathlib import Path
from http.server import ThreadingHTTPServer

from playwright.sync_api import expect, sync_playwright
from dashboard.routes import handler_for
from tests.unit import test_receipt_matching as fixtures
from PIL import Image
from reconciliation.duplicate_workflow import fingerprint


class ReceiptMatchingBrowserTests(unittest.TestCase):
    def test_combined_match_review_accept_reload_and_undo(self):
        """Use real local HTTP endpoints without sending documents to a model."""
        fixture = fixtures.ReceiptMatchingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        Image.new("RGB", (480, 800), "white").save(fixture.source)
        digest = fingerprint(fixture.source)
        fixture.index["documents"][digest] = fixture.index["documents"].pop(fixture.digest)
        fixture.state["units"][digest + ":0"] = fixture.state["units"].pop(fixture.key)
        (fixture.work / "index.json").write_text(json.dumps(fixture.index))
        fixture.state["index_sha256"] = fingerprint(fixture.work / "index.json")
        fixture.review.data = fixture.base / "dashboard-data"
        fixture.review.data.mkdir()
        fixture.review.root = fixture.base
        fixture.review.workflow_checks = lambda: (False, False, False)
        fixture.state.update(screens={}, pairs={})
        fixture.save_state()
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(fixture.review, "test-token"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/documents")
            page.get_by_role("link", name="Review extraction", exact=True).first.click()
            expect(page.locator("#receipt-pieces fieldset")).to_have_count(2)
            expect(page.locator("#original-preview img")).to_be_visible()
            expect(page.locator("#original-status")).to_have_text("Image 1")
            left = page.locator('.extraction-original').bounding_box()
            right = page.locator('.extraction-editor').bounding_box()
            self.assertLess(left['x'] + left['width'], right['x'])
            page.locator('#original-zoom').select_option('2')
            expect(page.locator('#original-preview')).to_have_attribute('style', 'width: 200%;')
            page.locator('#original-zoom').select_option('1')
            page.locator('#add-receipt').click()
            expect(page.locator('[data-field="total"]').last).to_have_value('')
            page.get_by_role('button', name='Remove this piece from extraction').last.click()
            artifacts = Path(__file__).resolve().parents[2] / '.tools'
            artifacts.mkdir(exist_ok=True)
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(artifacts / 'extraction-review.png'), full_page=True)
            expect(page.locator('[data-field="total"]').first).to_have_value("45.00")
            page.locator("#receipt-reviewer").fill("Fixture reviewer")
            page.locator("#accept-receipts").click()
            expect(page.locator("#receipt-unit-status")).to_have_text("Extraction accepted.")
            page.get_by_role("link", name="Back to document status").click()
            page.locator("#receipt-reviewer").fill("Fixture reviewer")
            page.locator("#receipt-bank").select_option("combined")
            expect(page.locator('#receipt-allocations input[type="checkbox"]')).to_have_count(2)
            for checkbox in page.locator('#receipt-allocations input[type="checkbox"]').all():
                checkbox.check()
            page.locator("#propose-receipt-match").click()
            expect(page.locator("#receipt-proposal")).to_contain_text("Supporting total: MYR 60.00")
            expect(page.locator("#receipt-proposal")).to_contain_text("Difference: MYR 0.00")
            expect(page.locator("#receipt-proposal")).to_contain_text("pending")
            page.locator("#receipt-proposal").get_by_role("button", name="Accept match", exact=True).click()
            expect(page.locator("#receipt-proposal")).to_contain_text("accepted")
            page.reload()
            expect(page.locator("#receipt-saved-matches")).to_contain_text("accepted")
            page.locator("#receipt-reviewer").fill("Fixture reviewer")
            page.locator("#receipt-saved-matches").get_by_role("button", name="Undo match", exact=True).click()
            expect(page.locator("#receipt-saved-matches")).to_contain_text("undone")
            expect(page.locator('#receipt-allocations input[type="checkbox"]')).to_have_count(2)
            page.locator("#receipt-bank").select_option("first")
            page.locator('#receipt-allocations input[type="checkbox"]').first.check()
            page.locator("#propose-receipt-match").click()
            expect(page.locator("#receipt-proposal")).to_contain_text("Supporting total: MYR 45.00")
            page.locator("#receipt-proposal").get_by_role("button", name="Accept match", exact=True).click()
            expect(page.locator("#receipt-proposal")).to_contain_text("accepted")
            page.locator("#receipt-bank").select_option("second")
            expect(page.locator('#receipt-allocations input[type="checkbox"]')).to_have_count(1)
            page.locator('#receipt-allocations input[type="checkbox"]').check()
            page.locator("#propose-receipt-match").click()
            expect(page.locator("#receipt-proposal")).to_contain_text("Supporting total: MYR 15.00")
            page.locator("#receipt-proposal").get_by_role("button", name="Accept match", exact=True).click()
            expect(page.locator("#receipt-proposal")).to_contain_text("accepted")
            self.assertFalse(errors)
            browser.close()
