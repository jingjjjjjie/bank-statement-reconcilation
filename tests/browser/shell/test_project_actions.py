"""Click workspace reset/delete through real HTTP using disposable original files."""

import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from reconciliation.intake.workspace import SourceSelection
from tests.browser import browser_options
from tests.http_server import TestServer


class ProjectActionsBrowserTests(unittest.TestCase):
    def test_reset_cancel_delete_and_mobile_layout(self):
        """Confirmation cancellation preserves data; successful actions retain originals."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / 'April'
            (work / 'documents').mkdir(parents=True)
            (work / 'statement').mkdir()
            document, statement = work / 'documents/receipt.txt', work / 'statement/bank.pdf'
            document.write_bytes(b'original receipt')
            statement.write_bytes(b'original bank')
            sources = SourceSelection(root, root / 'data')
            sources.save_workspace(work)
            manifest, _ = sources.start()
            output = manifest.parent / 'review/state.json'
            output.parent.mkdir()
            output.write_text('{"old":"review"}')
            server = TestServer(('127.0.0.1', 0), create_app(sources=sources))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(**browser_options())
                    try:
                        page = browser.new_page(viewport={'width': 1440, 'height': 900})
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(f'http://127.0.0.1:{server.server_port}/projects')
                        reset = page.get_by_role('button', name='Reset workspace April')
                        delete = page.get_by_role('button', name='Delete workspace April')
                        expect(reset).to_be_visible()
                        expect(delete).to_be_visible()
                        page.get_by_role('button', name='How to use this page').focus()
                        expect(page.get_by_role('tooltip')).to_contain_text('Close keeps progress')
                        page.keyboard.press('Escape')
                        screenshots = Path('.tools/workspace-actions')
                        screenshots.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(screenshots / 'desktop.png'), full_page=True)
                        page.once('dialog', lambda dialog: dialog.dismiss())
                        reset.click()
                        self.assertTrue(output.exists())
                        page.once('dialog', lambda dialog: dialog.accept())
                        reset.click()
                        expect(page.locator('#toast')).to_contain_text('Workspace reset')
                        expect(page.locator('.project-row')).to_have_count(1)
                        self.assertFalse(output.exists())
                        page.set_viewport_size({'width': 390, 'height': 844})
                        expect(reset).to_be_visible()
                        expect(delete).to_be_visible()
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        page.screenshot(path=str(screenshots / 'mobile.png'), full_page=True)
                        page.once('dialog', lambda dialog: dialog.dismiss())
                        delete.click()
                        expect(page.locator('.project-row')).to_have_count(1)
                        page.once('dialog', lambda dialog: dialog.accept())
                        delete.click()
                        expect(page.locator('.project-row')).to_have_count(0)
                        expect(page.get_by_text('No projects yet', exact=True)).to_be_visible()
                        page.reload()
                        expect(page.locator('.project-row')).to_have_count(0)
                        self.assertEqual(document.read_bytes(), b'original receipt')
                        self.assertEqual(statement.read_bytes(), b'original bank')
                        self.assertFalse(errors)
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()
