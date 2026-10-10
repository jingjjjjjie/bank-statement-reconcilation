"""Browser checks for token settings and gated completion display."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from dashboard.services.review import Review
from reconciliation.intake.duplicates import organize
from reconciliation.model.token_usage import summary
from tests.browser import browser_options
from tests.http_server import TestServer


class TokenBrowserTests(unittest.TestCase):
    def test_settings_and_final_page(self):
        """Show usage safely and keep final totals hidden before completion."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            usage = patch('dashboard.services.review.workspace_summary', return_value=summary(base / 'usage.jsonl'))
            usage.start()
            self.addCleanup(usage.stop)
            source = base / "sources"
            source.mkdir()
            (source / "a.txt").write_text("same", encoding="utf-8")
            (source / "b.txt").write_text("same", encoding="utf-8")
            manifest = base / "manifest.json"
            organize(source, manifest)
            server = TestServer(("127.0.0.1", 0), create_app(Review(manifest, base / "data"), "test-token"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(**browser_options())
                    page = browser.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    url = f"http://127.0.0.1:{server.server_port}"
                    page.goto(url + "/review")
                    expect(page).to_have_title("Exact duplicates · Accounting Copilot")
                    expect(page.locator("h1")).to_have_text("Exact duplicate review")
                    page.screenshot(path=".tools/formal-dashboard.png", full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                    page.goto(url + "/settings")
                    expect(page.locator("#token-usage")).to_contain_text("Workspace total 0")
                    expect(page.locator("#max-parallel")).to_have_value("4")
                    page.locator("#max-parallel").fill("2")
                    page.locator("#save-settings").click()
                    expect(page.locator("#save-state")).to_have_text("All settings saved")
                    page.reload()
                    expect(page.locator("#max-parallel")).to_have_value("2")
                    page.route(
                        "**/api/config",
                        lambda route: route.fulfill(
                            status=200,
                            content_type="application/json",
                            body=json.dumps(
                                {key: value for key, value in route.fetch().json().items() if key != "token_usage"}
                            ),
                        ),
                    )
                    page.reload()
                    expect(page.locator("#token-usage")).to_contain_text("server is restarted")
                    page.goto(url + "/complete")
                    expect(page).to_have_url(url + "/final-report")
                    expect(page.locator("#completion-title")).to_have_text("Final report")
                    expect(page.locator("#final-usage")).to_have_count(0)
                    work = base / "next-workspace"
                    next_source = work / "documents"
                    next_source.mkdir(parents=True)
                    (work / "statement").mkdir()
                    (next_source / "one.txt").write_text("duplicate", encoding="utf-8")
                    (next_source / "two.txt").write_text("duplicate", encoding="utf-8")
                    bank_pdf = work / "statement/statement.pdf"
                    bank_pdf.write_bytes(b"%PDF-1.4\nfixture")
                    page.goto(url + "/source")
                    expect(page.locator("h1")).to_have_text("Choose your workspace")
                    page.get_by_text("Enter a folder path manually", exact=True).click()
                    page.locator("#source-path").fill(str(work))
                    page.get_by_role("button", name="Select workspace").click()
                    expect(page.locator("#selected-source")).to_contain_text("2 supporting files")
                    self.assertTrue((next_source / "one.txt").exists())
                    expect(page.locator("#selected-source")).to_contain_text("1 bank statement")
                    self.assertTrue(bank_pdf.exists())
                    page.get_by_role("button", name="Proceed", exact=True).click()
                    expect(page).to_have_url(url + "/documents")
                    expect(page.locator('.rail a[href="/review"]')).to_have_count(0)
                    report = json.loads((work / "output/duplicates/report.json").read_text())
                    self.assertEqual(report["Summary"]["groups"], 1)
                    self.assertTrue(report["OrganizationComplete"])
                    for record in report["Files"]:
                        self.assertEqual(Path(record["OrganizedPath"]).read_bytes(), b"duplicate")
                    self.assertTrue((next_source / "one.txt").exists())
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
