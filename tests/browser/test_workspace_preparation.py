"""Verify first-page preparation progress without starting model extraction."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from reconciliation.source_selection import SourceSelection
from tests.browser import browser_options
from tests.http_server import TestServer


class WorkspacePreparationTests(unittest.TestCase):
    def test_progress_failures_retry_and_original_inputs(self):
        """Poll a locked preparation, retain warnings, retry, and reuse original extraction state."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            work = base / "Work"
            documents = work / "documents"
            documents.mkdir(parents=True)
            (work / "statement").mkdir()
            (work / "statement/bank.pdf").write_bytes(b"bank fixture")
            book = Workbook()
            book.active["A1"] = "Original Excel evidence"
            book.save(documents / "receipt.xlsx")
            original = (documents / "receipt.xlsx").read_bytes()
            (documents / "copy.xlsx").write_bytes(original)
            sources = SourceSelection(base, base / "data")
            app = create_app(None, "token", sources)
            server = TestServer(("127.0.0.1", 0), app)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            release = threading.Event()

            def held_conversion(source):
                """Hold one local conversion so the browser can observe live progress."""
                if not release.wait(15):
                    raise AssertionError("Progress did not arrive while preparation held the lock")
                raise ValueError("Conversion fixture failed; retry preview")

            try:
                with patch('dashboard.workspace_preparation.convert_excel_to_pdf', side_effect=held_conversion), \
                     patch('reconciliation.codex_reviewer.CodexReviewer.ask', side_effect=AssertionError('No model calls')), \
                     sync_playwright() as playwright:
                    browser = playwright.chromium.launch(**browser_options(), args=['--no-sandbox'])
                    try:
                        page = browser.new_page(viewport={"width": 1440, "height": 1000})
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(f'http://127.0.0.1:{server.server_port}/source')
                        page.get_by_text('Enter a folder path manually', exact=True).click()
                        page.locator('#source-path').fill(str(work))
                        page.locator('#select-source').click()
                        expect(page.locator('#start-source')).to_be_enabled()
                        page.locator('#start-source').click()
                        expect(page.locator('#preparation-stage')).to_have_text('Converting Excel previews')
                        expect(page.locator('#preparation-bar')).to_have_attribute('value', '25')
                        expect(page.locator('#start-source')).to_be_disabled()
                        self.assertTrue((work / 'output/duplicates/report.json').exists())
                        page.set_viewport_size({'width': 390, 'height': 844})
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        page.locator('#source-preparation').scroll_into_view_if_needed()
                        page.screenshot(full_page=True, path='/workspace/.tools/workspace-preparation.png' if os.name != 'nt'
                                        else str(Path('.tools/workspace-preparation.png').resolve()))
                        release.set()
                        expect(page.locator('#preparation-warnings')).to_contain_text('Conversion fixture failed', timeout=15000)
                        expect(page.locator('#prepare-source')).to_be_enabled()
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        review = app.state.context.review
                        saved = json.loads((review.manifest_path.parent / 'preview-status.json').read_text())
                        self.assertEqual(saved['files'][0]['status'], 'unresolved')
                        index_path = review.manifest_path.parent / 'review/index.json'
                        state_path = index_path.with_name('state.json')
                        before = (index_path.read_bytes(), state_path.read_bytes())
                        index = json.loads(before[0])
                        self.assertEqual(len(index['documents']), 1)
                        unit = next(iter(index['documents'].values()))
                        self.assertTrue(unit['paths'][0].endswith('.xlsx'))
                        self.assertIn('Original Excel evidence', unit['units'][0]['text'])
                        with patch('dashboard.workspace_preparation.convert_excel_to_pdf', return_value=base / 'display.pdf'):
                            page.locator('#prepare-source').click()
                            expect(page).to_have_url(f'http://127.0.0.1:{server.server_port}/documents', timeout=15000)
                        self.assertEqual(before, (index_path.read_bytes(), state_path.read_bytes()))
                        self.assertEqual((documents / 'receipt.xlsx').read_bytes(), original)
                        self.assertEqual((documents / 'copy.xlsx').read_bytes(), original)
                        self.assertFalse(errors)
                    finally:
                        release.set()
                        browser.close()
            finally:
                release.set()
                server.shutdown()
                server.server_close()
