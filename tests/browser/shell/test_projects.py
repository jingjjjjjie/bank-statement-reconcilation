"""Exercise the department portal and real saved project selection in the browser."""

import os
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from reconciliation.intake.workspace import SourceSelection
from tests.http_server import TestServer


class ProjectNavigationTests(unittest.TestCase):
    """Check the portal against synthetic workspaces without model calls."""

    def test_home_projects_selection_and_mobile_help(self):
        """Cards, search, cached selection, empty creation and mobile help work together."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = SourceSelection(root, root / "data")
            for name in ("April", "May", "June"):
                work = root / name
                (work / "documents").mkdir(parents=True)
                (work / "statement").mkdir()
                (work / "statement/bank.pdf").write_bytes(b"fixture")
                if name != "June":
                    sources.save_workspace(work)
                    sources.start()
            (root / "May/documents").rmdir()
            app = create_app(None, "token", sources)
            server = TestServer(("127.0.0.1", 0), app)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        headless=True,
                        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe"
                        if os.name == "nt" else None,
                    )
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    def capture(name):
                        """Optionally save synthetic screenshots for visual review."""
                        if os.environ.get("PROJECT_SCREENSHOTS"):
                            output = Path(os.environ["PROJECT_SCREENSHOTS"])
                            output.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(output / f"{name}.png"), full_page=True)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    base = f"http://127.0.0.1:{server.server_port}"
                    page.goto(base)
                    expect(page).to_have_url(base + "/accounting-finance")
                    expect(page.get_by_role("heading", name="Accounting and Finance", exact=True)).to_be_visible()
                    expect(page.locator(".page-help-button")).to_have_count(0)
                    expect(page.locator(".brand-identity span")).to_have_count(0)
                    capture("accounting-finance")
                    page.locator(".portal-card").click()
                    expect(page.locator(".project-row")).to_have_count(2)
                    capture("projects")
                    page.get_by_label("Status", exact=True).select_option("needs_attention")
                    expect(page.locator(".project-row")).to_have_count(1)
                    expect(page.locator(".project-row")).to_contain_text("May")
                    page.get_by_label("Status", exact=True).select_option("all")
                    page.get_by_label("Search projects").fill("April")
                    expect(page.locator(".project-row")).to_have_count(1)
                    self.assertIsNone(app.state.context.review)
                    page.get_by_role("button", name="Resume April").click()
                    expect(page).to_have_url(base + "/documents")
                    self.assertEqual(app.state.context.review.root, root / "April/documents")
                    expect(page.locator(".brand-identity span")).to_have_text("April")
                    page.locator('.app-header a[href="/projects"]').click()
                    expect(page.locator(".project-active")).to_have_text("Active workspace")
                    page.get_by_role("button", name="Resume April").click()
                    expect(page).to_have_url(base + "/documents")
                    page.locator('.app-header a[href="/projects"]').click()
                    page.get_by_role("button", name="New project", exact=True).click()
                    expect(page.get_by_role("dialog", name="New project", exact=True)).to_be_visible()
                    expect(page.locator("#workspace-name")).to_have_text("Choose a folder to begin")
                    expect(page.locator("#source-action")).to_be_hidden()
                    page.keyboard.press("Escape")
                    expect(page.get_by_role("dialog", name="New project", exact=True)).to_be_hidden()
                    expect(page.get_by_role("button", name="New project", exact=True)).to_be_focused()
                    page.set_viewport_size({"width": 390, "height": 844})
                    expect(page.locator(".project-row")).to_have_count(2)
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                    expect(page.locator("nav")).to_have_count(1)
                    expect(page.locator(".page-help-button")).to_have_count(1)
                    expect(page.get_by_role("link", name="Home", exact=True)).to_have_count(0)
                    expect(page.get_by_role("link", name="Projects", exact=True)).to_have_count(0)
                    page.locator(".page-help-button").focus()
                    expect(page.get_by_role("tooltip")).to_be_visible()
                    page.keyboard.press("Escape")
                    expect(page.get_by_role("tooltip")).to_be_hidden()
                    page.get_by_label("Search projects").fill("missing")
                    expect(page.get_by_text("No matching projects", exact=True)).to_be_visible()
                    page.reload()
                    expect(page.locator(".project-row")).to_have_count(2)
                    page.get_by_role("button", name="New project", exact=True).click()
                    expect(page.get_by_role("dialog", name="New project", exact=True)).to_be_visible()
                    page.locator(".manual-path summary").click()
                    page.locator("#source-path").fill(str(root / "June"))
                    page.locator("#select-source").click()
                    expect(page.locator("#start-source")).to_be_enabled()
                    capture("new-project-mobile")
                    self.assertTrue(page.locator(".project-dialog").evaluate("el => el.scrollWidth <= el.clientWidth"))
                    page.locator("#start-source").click()
                    expect(page).to_have_url(base + "/documents")
                    self.assertEqual(app.state.context.review.root, root / "June/documents")
                    page.locator('.app-header a[href="/projects"]').click()
                    expect(page.locator(".project-row")).to_have_count(3)
                    back = page.get_by_role("link", name="Back to Home")
                    self.assertEqual(back.evaluate("el => getComputedStyle(el).textDecorationLine"), "none")
                    back.hover()
                    self.assertEqual(back.evaluate("el => getComputedStyle(el).textDecorationLine"), "none")
                    page.get_by_role("link", name="Back to Home").click()
                    expect(page).to_have_url(base + "/accounting-finance")
                    expect(page.locator(".portal-card")).to_be_visible()
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
