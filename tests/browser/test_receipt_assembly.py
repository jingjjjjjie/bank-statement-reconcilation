"""Exercise manual receipt boundaries with real dashboard controls."""
import json
import threading
import unittest
from tests.http_server import TestServer

from playwright.sync_api import expect, sync_playwright
from dashboard.routes import create_app
from tests.browser import browser_options
from reconciliation.duplicate_workflow import fingerprint
from reconciliation.receipt_assembly import input_revision
from tests.unit import test_receipt_matching as fixtures
from tests.unit.test_receipt_assembly import piece


class ReceiptAssemblyBrowserTests(unittest.TestCase):
    def test_add_remove_and_accept_document(self):
        """Correct boundaries without adding repeated totals or losing page references."""
        fixture = fixtures.ReceiptMatchingTests()
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
        fixture.state["assemblies"] = {fixture.digest: {"receipts": [piece([1]), piece([2])],
            "reviewed_units": [1, 2], "limitations": [], "input_revision": input_revision(document, fixture.state)}}
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
            link = page.locator("#document-rows").get_by_role("link", name="Review results", exact=True)
            link.first.click()
            expect(page.locator("#receipt-pieces fieldset")).to_have_count(2)
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
            page.locator('[data-boundary-review]').uncheck()
            page.locator('#accept-receipts').click()
            expect(page.locator('#receipt-unit-status')).to_contain_text("Extraction accepted.")
            page.reload()
            expect(page.locator('[data-field="total"]')).to_have_value("45.00")
            expect(page.locator('[data-field="source_units"]')).to_have_value("1\n2")
            self.assertFalse(errors)
            browser.close()
