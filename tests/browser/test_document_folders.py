"""Exercise original folder navigation without changing extraction state."""

import threading
import unittest

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from tests.browser import browser_options
from tests.http_server import TestServer


class DocumentFolderTests(unittest.TestCase):
    def test_folders_duplicates_search_and_collapse(self):
        """Keep exact copies visible, grey and grouped under searchable folder names."""
        server = TestServer(('127.0.0.1', 0), create_app(token='fixture'))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        paths = ['/work/documents/350.00/receipt.pdf', '/work/documents/350.00/copies/copy.pdf']
        rows = [
            {
                'id': 'a',
                'name': 'receipt.pdf',
                'path': paths[0],
                'paths': paths,
                'status': 'Complete',
                'extracted': True,
            },
            {
                'id': 'b',
                'name': 'other.pdf',
                'path': '/work/documents/other.pdf',
                'paths': ['/work/documents/other.pdf'],
                'status': 'Queued',
            },
        ]

        def respond(route):
            """Supply two unique documents and three source locations."""
            path = route.request.url.split('/api/')[1]
            data = {
                'session': {'active': True, 'review_id': 'fixture', 'token': 'fixture'},
                'workspace': {'name': 'Fixture', 'period': ''},
                'workflow-checks': {'steps': []},
                'development-mode': {'enabled': False},
                'document-status': {'prepared': True, 'source_root': '/work/documents', 'documents': rows},
                'content/execution': {'running': False},
            }.get(path, {})
            route.fulfill(json=data)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page(viewport={'width': 1440, 'height': 960})
            page.route('**/api/**', respond)
            page.goto(f'http://127.0.0.1:{server.server_port}/documents')
            expect(page.locator('.document-file')).to_have_count(3)
            expect(page.locator('.document-folder')).to_have_count(3)
            expect(page.locator('.document-folder svg')).to_have_count(3)
            expect(page.locator('.duplicate-file')).to_contain_text('copy.pdf')
            expect(page.locator('.duplicate-file .document-status')).to_have_text('Exact duplicate')
            expect(page.locator('.duplicate-file')).to_have_css('background-color', 'rgb(244, 244, 243)')
            expect(page.locator('#document-total')).to_have_text('2')
            page.get_by_role('button', name='Collapse folder 350.00', exact=True).click()
            expect(page.locator('.document-file')).to_have_count(1)
            page.locator('#document-search').fill('copies')
            expect(page.locator('.document-file')).to_have_count(1)
            expect(page.locator('.duplicate-file')).to_be_visible()
            page.locator('#document-search').fill('')
            expect(page.locator('.document-file')).to_have_count(1)
            page.get_by_role('button', name='Expand folder 350.00', exact=True).click()
            expect(page.locator('.document-file')).to_have_count(3)
            page.locator('#document-filter').select_option('duplicate')
            expect(page.locator('.document-file')).to_have_count(1)
            page.get_by_role('button', name='Collapse folder copies', exact=True).click()
            expect(page.locator('.document-file')).to_have_count(0)
            page.get_by_role('button', name='Expand folder copies', exact=True).click()
            expect(page.locator('.document-file')).to_have_count(1)
            page.set_viewport_size({'width': 390, 'height': 844})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            browser.close()
