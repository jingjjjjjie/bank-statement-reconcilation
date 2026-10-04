"""Exercise the Completion ZIP download and error handling on desktop and mobile."""

import io
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from dashboard.services.matching import final_review
from tests.browser import browser_options
from tests.fixtures.final_review import FinalReviewFixture
from tests.http_server import TestServer


class UnmatchedExportBrowserTests(unittest.TestCase):
    """Use temporary source files and approvals, including an incomplete workflow."""

    def test_completion_download_and_failure(self):
        """Both screen sizes download the real ZIP without altering ledger or inputs."""
        fixture = FinalReviewFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.write(
            fixture.review.manifest_path,
            {
                'SupportingRoot': str(fixture.review.root),
                'Files': [],
                'Mode': 'exact_report',
            },
        )
        fixture.review.manifest = final_review.read(fixture.review.manifest_path)
        fixture.review.workspace = lambda: {'name': 'Synthetic workspace', 'period': 'December 2025'}
        fixture.review.workflow_checks = lambda: (False, False, False)
        fixture.review.completion = lambda: {
            'exact_done': True,
            'content_done': True,
            'bank_done': False,
            'complete': False,
        }
        final_review.decide(fixture.review, fixture.request(allocations=[{'item_id': 'D1', 'amount': '4'}]))
        ledger_path = fixture.project / 'final-review/decisions.json'
        before = ledger_path.read_bytes()
        (fixture.review.root.parent / 'statement').mkdir()
        (fixture.review.root.parent / 'statement/bank.pdf').write_bytes(b'Original statement')
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test-token', SimpleNamespace()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{server.server_port}/complete')
            expect(page.locator('#completion-title')).to_have_text('Final report')
            page.get_by_role('button', name='Export', exact=True).click()
            button = page.get_by_role('button', name='Export unmatched documents')
            for width in (1440, 390):
                page.set_viewport_size({'width': width, 'height': 900})
                expect(page.get_by_role('navigation')).to_have_count(1)
                help_button = page.get_by_role('button', name='How to use this page')
                expect(help_button).to_have_count(1)
                page.get_by_role('button', name='Close export').click()
                help_button.focus()
                expect(help_button).to_have_attribute('aria-expanded', 'true')
                page.keyboard.press('Escape')
                expect(help_button).to_have_attribute('aria-expanded', 'false')
                page.get_by_role('button', name='Export', exact=True).click()
                with page.expect_download() as download:
                    button.click()
                self.assertEqual(download.value.suggested_filename, 'unmatched-documents.zip')
                with ZipFile(io.BytesIO(Path(download.value.path()).read_bytes())) as archive:
                    self.assertEqual(archive.namelist(), ['uploads/', 'uploads/receipt-2.txt'])
                expect(button).to_be_enabled()
                for kind, filename, expected in [
                    ('original', 'original-documents.zip', {'documents/receipt-1.txt', 'documents/receipt-2.txt'}),
                    ('matched', 'matched-documents.zip', {'documents/receipt-1.txt'}),
                    ('project', 'original-project.zip', {'uploads/documents/receipt-1.txt', 'uploads/documents/receipt-2.txt', 'uploads/statement/bank.pdf'}),
                ]:
                    with page.expect_download() as source_download:
                        page.locator('#export-' + kind).click()
                    self.assertEqual(source_download.value.suggested_filename, filename)
                    with ZipFile(source_download.value.path()) as archive:
                        self.assertEqual({name for name in archive.namelist() if not name.endswith('/')}, expected)
                    expect(page.locator('#' + kind + '-export-status')).to_have_text('ZIP downloaded.')
                expect(page.locator('.header-links a').last).to_have_attribute('href', '/final-report')
                expect(page.locator('#unmatched-export-status')).to_have_text('ZIP downloaded.')
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
            page.route(
                '**/api/unmatched-documents-export',
                lambda route: route.fulfill(
                    status=400,
                    json={'error': 'Document changed during export; retry.'},
                ),
            )
            button.click()
            expect(page.locator('#unmatched-export-status')).to_have_text('Document changed during export; retry.')
            expect(button).to_be_enabled()
            self.assertEqual(ledger_path.read_bytes(), before)
            self.assertEqual(len(list(fixture.review.root.iterdir())), 2)
            page.get_by_role('button', name='Close export').click()
            expect(page.get_by_role('link', name='Review Matching', exact=False)).to_have_attribute('aria-disabled', 'true')
            page.goto(f'http://127.0.0.1:{server.server_port}/matching')
            expect(page).to_have_url(f'http://127.0.0.1:{server.server_port}/bank')
            page.goto(f'http://127.0.0.1:{server.server_port}/extraction-review')
            expect(page).to_have_url(f'http://127.0.0.1:{server.server_port}/documents')
            browser.close()
