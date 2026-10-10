"""Exercise original folder navigation without changing extraction state."""

import threading
import unittest

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from tests.browser import browser_options
from tests.http_server import TestServer


class DocumentFolderTests(unittest.TestCase):
    def test_folders_duplicates_and_search(self):
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
            expect(page.locator('.duplicate-file')).to_have_css('background-color', 'rgb(238, 238, 238)')
            expect(page.locator('#document-total')).to_have_text('2')
            # Extraction totals must not shrink or offset the Documents summary.
            for width, height, size in ((1536, 760, '21px'), (390, 844, '18px')):
                page.set_viewport_size({'width': width, 'height': height})
                for metric in ('document-total', 'document-admin', 'document-complete'):
                    expect(page.locator(f'#{metric}')).to_have_css('font-size', size)
                    expect(page.locator(f'#{metric}')).to_have_css('margin-left', '0px')
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.set_viewport_size({'width': 1440, 'height': 960})
            expect(page.locator('.document-folder button, .folder-arrow')).to_have_count(0)
            expect(page.locator('.duplicate-file strong')).to_have_css('color', 'rgb(115, 115, 115)')
            page.locator('#document-search').fill('copies')
            expect(page.locator('.document-file')).to_have_count(1)
            expect(page.locator('.duplicate-file')).to_be_visible()
            page.locator('#document-search').fill('')
            expect(page.locator('.document-file')).to_have_count(3)
            page.locator('#document-filter').select_option('excluded')
            expect(page.locator('.document-file')).to_have_count(1)
            # Group processing states without hiding duplicate or rejected source files.
            for index, status in enumerate(('Processing', 'Needs review', 'Trash', 'Needs attention')):
                path = f'/work/documents/state-{index}.pdf'
                rows.append({'id': f'state-{index}', 'name': f'state-{index}.pdf',
                             'path': path, 'paths': [path], 'status': status})
            page.reload()
            expect(page.locator('#document-filter option')).to_have_count(5)
            for category, count in (('all', 7), ('review', 3), ('complete', 1), ('attention', 1), ('excluded', 2)):
                page.locator('#document-filter').select_option(category)
                expect(page.locator('.document-file')).to_have_count(count)
            page.set_viewport_size({'width': 390, 'height': 844})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            browser.close()
