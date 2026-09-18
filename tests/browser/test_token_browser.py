"""Browser checks for token settings and gated completion display."""
import json
import tempfile
import threading
import unittest
from tests.http_server import TestServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from dashboard.app import Review, create_app
from reconciliation.duplicate_workflow import organize


class TokenBrowserTests(unittest.TestCase):
    def test_settings_and_final_page(self):
        """Show usage safely and keep final totals hidden before completion."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
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
                    browser = playwright.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe", headless=True)
                    page = browser.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    url = f"http://127.0.0.1:{server.server_port}"
                    page.goto(url + "/review")
                    expect(page).to_have_title("Exact duplicates · Bank Statement Reconciliation")
                    expect(page.locator("h1")).to_have_text("Exact duplicate review")
                    page.screenshot(path=".tools/formal-dashboard.png", full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                    page.goto(url + "/settings")
                    expect(page.locator("#token-usage")).to_contain_text("Total 0")
                    expect(page.locator("#max-parallel")).to_have_value("4")
                    page.locator("#max-parallel").fill("2")
                    page.locator("#save-settings").click()
                    expect(page.locator("#save-state")).to_have_text("All settings saved")
                    page.reload()
                    expect(page.locator("#max-parallel")).to_have_value("2")
                    page.route("**/api/config", lambda route: route.fulfill(status=200, content_type="application/json",
                               body=json.dumps({key: value for key, value in route.fetch().json().items() if key != "token_usage"})))
                    page.reload()
                    expect(page.locator("#token-usage")).to_contain_text("server is restarted")
                    page.goto(url + "/complete")
                    expect(page.locator("#completion-title")).to_have_text("Workflow in progress.")
                    expect(page.locator("#final-usage")).to_be_hidden()
                    page.route("**/api/completion", lambda route: route.fulfill(status=200, content_type="application/json",
                               body=json.dumps({"exact_done": True, "content_done": True, "bank_done": True,
                                                "complete": True, "token_usage": {"totals": {
                                                    "input_tokens": 100, "cached_input_tokens": 40,
                                                    "output_tokens": 25, "reasoning_output_tokens": 5},
                                                    "attempts": 1, "unknown_attempts": 0, "cache_hits": 0,
                                                    "by_stage": {"pdf": {"input_tokens": 100, "output_tokens": 25}},
                                                    "by_model": {"test": {"input_tokens": 100, "output_tokens": 25}}}})))
                    page.reload()
                    expect(page.locator("#final-total")).to_have_text("125 tokens")
                    expect(page.locator("#final-usage")).to_be_visible()
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
