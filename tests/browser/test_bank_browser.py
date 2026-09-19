"""Smoke test the bank page against temporary data in a real browser."""
import tempfile
import threading
import unittest
from tests.http_server import TestServer
from tests.browser import browser_options
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

from dashboard.app import Review, create_app
from reconciliation.duplicate_workflow import organize


class BankBrowserTests(unittest.TestCase):
    def test_bank_page_renders_and_filters_rows(self):
        """Render the saved statement and search its transaction narration."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "sources"
            source.mkdir()
            (source / "receipt.txt").write_text("fixture", encoding="utf-8")
            manifest = base / "manifest.json"
            organize(source, manifest)
            bank = base / "bank-output"
            bank.mkdir()
            (bank / "master_statement.csv").write_text(
                "account,currency,opening_balance,closing_balance,total_money_in,total_money_out,balance_checks,transaction_id,date,page,direction,money_in,money_out,balance,counterparty,counterparty_role,narration,matching_status\n"
                "8866,MYR,100.00,110.00,10.00,0.00,passed,tx-1,2025-12-01,2,in,10.00,0.00,110.00,Payer,payer,Unique transfer,pending\n",
                encoding="utf-8")
            review = Review(manifest, base / "dashboard-data")
            server = TestServer(("127.0.0.1", 0), create_app(review, "test-token"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(**browser_options())
                    try:
                        page = browser.new_page()
                        page.goto(f"http://127.0.0.1:{server.server_port}/bank")
                        expect(page.locator("#bank-count")).to_have_text("1")
                        page.get_by_role("button", name="Check bank extraction").click()
                        expect(page.locator("#bank-step-note")).to_contain_text("Finish documents")
                        expect(page.locator("#bank-next")).to_be_hidden()
                        expect(page.locator("#bank-rows tr")).to_have_count(1)
                        page.locator("#bank-search").fill("Unique transfer")
                        expect(page.locator("#bank-rows tr")).to_have_count(1)
                        page.locator("#bank-search").fill("not present")
                        expect(page.locator("#bank-rows tr")).to_have_count(0)
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
