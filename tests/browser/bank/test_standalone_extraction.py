"""Check standalone extraction, downloads, isolation and responsive navigation."""

import base64
import io
import tempfile
import threading
import unittest
from pathlib import Path

from openpyxl import load_workbook
from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from reconciliation.bank.statement import extract
from reconciliation.intake.workspace import SourceSelection
from statement_extraction.statement import extract as standalone_extract
from tests.browser import browser_options
from tests.fixtures.bank_pdf import ambank_statement, statement, uob_export
from tests.http_server import TestServer


class StandaloneExtractionTests(unittest.TestCase):
    def test_copy_and_api_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for bank in ('public_bank', 'maybank', 'hong_leong', 'cimb', 'ambank', 'uob'):
                path = root / f'{bank}.pdf'
                if bank == 'ambank':
                    ambank_statement(path)
                elif bank == 'uob':
                    uob_export(path)
                else:
                    statement(path, bank)
                self.assertEqual(standalone_extract(path, 2025, 'auto'), extract(path, 2025, 'auto'))
            app = create_app(None, 'token', SourceSelection(root, root / 'data'))
            server = TestServer(('127.0.0.1', 0), app)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            with sync_playwright() as playwright:
                client = playwright.request.new_context(base_url=f'http://127.0.0.1:{server.server_port}')
                token = client.get('/api/session').json()['token']
                payload = dict(filename='maybank.pdf', content=base64.b64encode((root / 'maybank.pdf').read_bytes()).decode(), year=2025, company='Example', bank='auto')
                self.assertEqual(client.post('/api/statement-extraction', data=payload).status, 403)
                headers = {'X-Review-Token': token}
                response = client.post('/api/statement-extraction', data=payload, headers=headers)
                self.assertEqual(response.status, 200, response.text())
                result = response.json()
                self.assertEqual(result['statement']['bank'], 'maybank')
                self.assertEqual(load_workbook(io.BytesIO(base64.b64decode(result['xlsx']))).active['A1'].value, 'Example')
                self.assertNotIn(directory, base64.b64decode(result['csv']).decode('utf-8-sig'))
                self.assertFalse(client.get('/api/session').json()['active'])
                payload['bank'] = 'cimb'
                self.assertEqual(client.post('/api/statement-extraction', data=payload, headers=headers).status, 400)

    def test_browser_upload_download_and_mobile_help(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = statement(root / 'maybank.pdf', 'maybank', mention='CIMB BANK BERHAD')
            app = create_app(None, 'token', SourceSelection(root, root / 'data'))
            server = TestServer(('127.0.0.1', 0), app)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(**browser_options())
                    page = browser.new_page(viewport={'width': 1280, 'height': 850})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    base = f'http://127.0.0.1:{server.server_port}'
                    page.goto(base + '/home')
                    page.get_by_role('link', name='Bank Statement Extraction').click()
                    expect(page.get_by_role('navigation').get_by_role('link')).to_have_count(1)
                    page.get_by_label('Bank statement PDF').set_input_files(str(path))
                    page.get_by_label('Statement year').fill('2025')
                    page.get_by_label('Company name').fill('Example')
                    page.get_by_role('button', name='Extract', exact=True).click()
                    expect(page.get_by_role('button', name='Download Excel')).to_be_visible(timeout=30000)
                    for kind in ('Excel', 'CSV'):
                        with page.expect_download() as download:
                            page.get_by_role('button', name=f'Download {kind}').click()
                        self.assertTrue(Path(download.value.path()).stat().st_size)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.get_by_role('button', name='How to use this page').click()
                    expect(page.get_by_role('tooltip')).to_be_visible()
                    page.keyboard.press('Escape')
                    expect(page.get_by_role('tooltip')).to_be_hidden()
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    page.get_by_role('link', name='Back to Home').click()
                    expect(page).to_have_url(base + '/home')
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
