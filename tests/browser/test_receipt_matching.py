"""Exercise the receipt split and combined match flow in Chromium with fixture data."""
import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import expect, sync_playwright
from dashboard.routes import handler_for
from tests.unit import test_receipt_matching as fixtures


class ReceiptMatchingBrowserTests(unittest.TestCase):
    def test_combined_match_review_accept_reload_and_undo(self):
        """Use real local HTTP endpoints without sending documents to a model."""
        fixture = fixtures.ReceiptMatchingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
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
            expect(page.locator("#receipt-pieces fieldset")).to_have_count(2)
            expect(page.locator('[data-field="total"]').first).to_have_value("45.00")
            page.locator("#receipt-reviewer").fill("Fixture reviewer")
            page.locator("#accept-receipts").click()
            expect(page.locator("#receipt-unit-status")).to_have_text("Extraction accepted.")
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
