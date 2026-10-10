"""Exercise manual receipt boundaries with real dashboard controls."""

import json
import threading
import unittest

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from reconciliation.extraction.pipeline.assembly import input_revision
from reconciliation.intake.duplicates import fingerprint
from tests.browser import browser_options
from tests.fixtures import receipt_review as receipt_review_fixture
from tests.fixtures.assembly import piece
from tests.http_server import TestServer


class ReceiptAssemblyBrowserTests(unittest.TestCase):
    def test_add_remove_and_accept_document(self):
        """Correct boundaries without adding repeated totals or losing page references."""
        fixture = receipt_review_fixture.ReceiptReviewFixture()
        fixture.setUp()
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {"name": "Fixture", "period": "December"}
        fixture.review.workflow_checks = lambda: (False, False, False)
        self.addCleanup(fixture.doCleanups)
        document = fixture.index["documents"][fixture.digest]
        document["id"] = fixture.digest
        document["units"].append({"label": "page 2", "image": None})
        (fixture.work / "index.json").write_text(json.dumps(fixture.index))
        fixture.state["index_sha256"] = fingerprint(fixture.work / "index.json")
        fixture.state["units"][fixture.digest + ":1"] = fixture.state["units"][fixture.key]
        fixture.state["assemblies"] = {
            fixture.digest: {
                "receipts": [piece([1]), piece([2])],
                "reviewed_units": [1, 2],
                "limitations": [],
                "input_revision": input_revision(document, fixture.state),
            }
        }
        fixture.review.data = fixture.base / "dashboard-data"
        fixture.review.data.mkdir()
        fixture.review.root = fixture.base
        fixture.review.workflow_checks = lambda: (False, False, False)
        fixture.state.update(screens={}, pairs={})
        fixture.save_state()
        server = TestServer(("127.0.0.1", 0), create_app(fixture.review, "test-token"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options(), args=["--no-sandbox"])
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/documents")
            link = page.locator("#document-rows").get_by_role("link", name="Review Extraction", exact=True)
            link.first.click()
            expect(page.locator("#receipt-pieces fieldset")).to_have_count(2)
            amounts = page.locator('[data-field="total"]')
            currencies = page.locator('select[data-field="currency"]')
            amounts.nth(0).fill('0.10')
            amounts.nth(1).fill('0.20')
            currencies.nth(0).select_option('MYR')
            currencies.nth(1).select_option('MYR')
            expect(page.locator('#document-total')).to_have_text('Document total: MYR 0.30')
            currencies.nth(1).select_option('USD')
            expect(page.locator('#document-total')).to_have_text('Document total: MYR 0.10 / USD 0.20')
            amounts.nth(1).fill('')
            expect(page.locator('#document-total')).to_have_text('Document total: MYR 0.10 (incomplete)')
            page.get_by_role("button", name="Select piece 2", exact=True).click()
            expect(page.get_by_role("button", name="Merge with previous receipt")).to_have_count(0)
            page.get_by_role("button", name="Remove this piece from extraction").click()
            expect(page.locator("#receipt-pieces fieldset")).to_have_count(1)
            page.locator('.piece-details summary').click()
            page.locator('[data-field="source_units"]').fill("1\n2")
            expect(page.get_by_role("button", name="Split receipt", exact=True)).to_have_count(0)
            page.locator("#add-receipt").click()
            expect(page.locator("#receipt-pieces fieldset")).to_have_count(2)
            page.get_by_role("button", name="Remove this piece from extraction").click()
            page.locator('[data-field="total"]').fill("45.00")
            expect(page.get_by_label('Pay to', exact=True)).to_be_visible()
            expect(page.get_by_label('Pay from', exact=True)).to_be_visible()
            page.get_by_label('Short description', exact=True).fill('Office supplies')
            page.get_by_label('Document no.', exact=True).fill('INV-123')
            page.locator('select[data-field="currency"]').select_option('CNY')
            expect(page.locator('#document-total')).to_have_text('Document total: CNY 45.00')
            expect(page.locator('[data-boundary-review]')).to_have_count(0)
            page.locator('#accept-receipts').click()
            expect(page.locator('#document-review-status')).to_have_attribute('aria-label', 'Extraction accepted')
            page.reload()
            expect(page.locator('[data-field="total"]')).to_have_value("45.00")
            expect(page.locator('[data-field="source_units"]')).to_have_value("1\n2")
            expect(page.get_by_label('Short description', exact=True)).to_have_value('Office supplies')
            expect(page.get_by_label('Document no.', exact=True)).to_have_value('INV-123')
            expect(page.locator('select[data-field="currency"]')).to_have_value('CNY')
            expect(page.locator('#document-total')).to_have_text('Document total: CNY 45.00')
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.get_by_label('Short description', exact=True)).to_be_visible()
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
            page.screenshot(path='duplicated/inspection/extraction-fields.png', full_page=True)
            self.assertFalse(errors)
            browser.close()
