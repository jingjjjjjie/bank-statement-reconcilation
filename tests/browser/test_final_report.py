"""Verify the read-only report and modal against synthetic original evidence."""
import csv
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest

import pymupdf
from playwright.sync_api import expect, sync_playwright

from dashboard import matching_review as matching
from dashboard.routes import create_app
from reconciliation.duplicate_workflow import fingerprint
from tests.browser import browser_options
from tests.http_server import TestServer
from tests.unit import test_matching_review as fixtures


def fake_pdf(path, title, lines, pages=1):
    """Create clearly labelled fake bank and receipt pages for preview checks."""
    with pymupdf.open() as document:
        for number in range(pages):
            page = document.new_page(width=595, height=650)
            page.insert_text((40, 45), 'SYNTHETIC DEMO / NOT A REAL FINANCIAL DOCUMENT', fontsize=10)
            page.insert_text((40, 100), title, fontsize=22)
            for index, line in enumerate(lines):
                page.insert_text((40, 150 + index * 32), line, fontsize=13)
            page.insert_text((40, 610), f'Page {number + 1}', fontsize=10)
        document.save(path)


class FinalReportBrowserTests(unittest.TestCase):
    def test_return_keeps_rows_and_evidence_position(self):
        """Back navigation keeps rows during refresh and restores PDF page and zoom."""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page()
            page.goto(self.url + '/final-report')
            expect(page.locator('.report-table tbody tr')).to_have_count(3)
            page.get_by_label('Find a transaction').fill('Cedar')
            page.get_by_role('button', name='View evidence for B1').click()
            page.get_by_label('Bank statement page', exact=True).select_option('0')
            page.get_by_label('Bank statement zoom', exact=True).select_option('150')
            page.get_by_role('button', name='Close evidence').click()
            page.locator('.app-header a[href="/matching"]').click()
            expect(page).to_have_url(self.url + '/matching')
            saved = page.request.get(self.url + '/api/matching').json()
            pending = []
            page.route('**/api/matching', lambda route: pending.append(route))
            page.go_back()
            expect(page.get_by_label('Find a transaction')).to_have_value('Cedar')
            expect(page.locator('.report-table tbody tr')).to_have_count(1)
            expect(page.locator('.final-report')).to_have_attribute('aria-busy', 'true')
            self.assertTrue(pending)
            pending.pop().fulfill(status=200, content_type='application/json', body=json.dumps(saved))
            page.get_by_role('button', name='View evidence for B1').click()
            expect(page.get_by_label('Bank statement page', exact=True)).to_have_value('0')
            expect(page.get_by_label('Bank statement zoom', exact=True)).to_have_value('150')
            browser.close()

    def setUp(self):
        """Use a temporary cache and saved decisions; never touch live review data."""
        fixture = fixtures.MatchingReviewTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        facts = matching.read(fixture.cache / 'facts.json')
        index = matching.read(fixture.cache / 'index.json')
        statement = fixture.root / 'demo-statement.pdf'
        fake_pdf(statement, 'DEMO BANK | December 2025', [
            'Date              Description                         Debit (MYR)',
            '01 Dec           Cedar Office Supplies             10.00',
            '02 Dec           Demo Courier                         10.00',
            '03 Dec           Unidentified transfer                5.00',
            'Total outgoing                                             25.00'], pages=2)
        master = fixture.project / 'bank-output/master_statement.csv'
        with master.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['sequence', 'source', 'page', 'balance_checks'])
            writer.writeheader()
            writer.writerows({'sequence': n, 'source': str(statement), 'page': 2, 'balance_checks': 'passed'} for n in (1, 2, 3))
        facts.update(statement_hash=fingerprint(statement), bank_hash=fingerprint(master))
        for number, old_digest in enumerate(list(index['documents']), 1):
            source = fixture.review.root / f'demo-receipt-{number}.pdf'
            fake_pdf(source, f'Cedar Office Supplies | Receipt {number}', [
                f'Reference: DEMO-2025-00{number}', 'Date: 01 December 2025',
                'Office stationery                                  MYR 10.00',
                'Total paid                                             MYR 10.00',
                'Thank you. This receipt is synthetic test evidence.'])
            digest = fingerprint(source)
            index['documents'][digest] = {'paths': [str(source)], 'units': [{'label': 'Page 1', 'text': 'Demo receipt'}]}
            del index['documents'][old_digest]
            for item in facts['items']:
                if item['document'] == old_digest:
                    item['document'] = digest
        for bank, party in zip(facts['banks'], ['Cedar Office Supplies', 'Demo Courier', 'Unidentified transfer']):
            bank['parties'] = [party]
        fixture.write(fixture.cache / 'facts.json', facts)
        fixture.write(fixture.cache / 'index.json', index)
        matching.decide(fixture.review, fixture.request(allocations=[{'item_id': 'D1', 'amount': '4'}, {'item_id': 'D2', 'amount': '6'}], note='Two stationery purchases; remaining receipt balances paid separately.'))
        matching.decide(fixture.review, fixture.request(bank='B2', action='deny', note='Courier receipt not supplied.'))
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {'name': 'Synthetic December 2025', 'period': 'Demo data'}
        fixture.review.workflow_checks = lambda: (False, False, False)
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test-token', SimpleNamespace()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f'http://127.0.0.1:{server.server_port}'

    def capture(self, page, name):
        """Optionally save reproducible audit screenshots outside tracked source."""
        if directory := os.environ.get('FINAL_REPORT_SCREENSHOTS'):
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(path / name), full_page=True)

    def test_report_popup_filters_downloads_and_mobile(self):
        """Saved approvals drive previews; modal actions preserve filters and ledger."""
        ledger = (self.fixture.project / 'final-review/decisions.json').read_bytes()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.url + '/final-report')
            expect(page.locator('.report-table tbody tr')).to_have_count(3)
            expect(page.get_by_text('1 transaction still needs review.', exact=False)).to_be_visible()
            self.capture(page, '01-final-report.png')
            page.get_by_label('Support status', exact=True).select_option('Supporting')
            page.get_by_label('Find a transaction').fill('Cedar')
            trigger = page.get_by_role('button', name='View evidence for B1')
            trigger.click()
            dialog = page.get_by_role('dialog')
            expect(dialog).to_be_visible()
            expect(dialog.locator('img')).to_have_count(2)
            for image in dialog.locator('img').all():
                expect(image).to_have_js_property('complete', True)
                self.assertGreater(image.evaluate('(img) => img.naturalWidth'), 0)
            expect(page.get_by_label('Bank statement page', exact=True)).to_have_value('1')
            expect(dialog.locator('.evidence-summary')).to_contain_text('MYR 0.00')
            self.capture(page, '02-evidence-popup.png')
            page.get_by_label('Bank statement page', exact=True).select_option('0')
            page.get_by_label('Bank statement zoom', exact=True).select_option('150')
            expect(dialog.locator('img').first).to_have_attribute('src', '/api/matching-image?kind=bank&id=B1&page=0')
            page.get_by_role('button', name='2. demo-receipt-2.pdf', exact=False).click()
            expect(dialog.get_by_role('heading', name='demo-receipt-2.pdf')).to_be_visible()
            with page.expect_download() as download:
                dialog.get_by_role('region', name='Approved supporting evidence', exact=True).get_by_role('link', name='Download original').click()
            self.assertIn('demo-receipt-2.pdf', download.value.suggested_filename)
            for _ in range(18):
                page.keyboard.press('Tab')
                self.assertTrue(page.evaluate('document.querySelector("dialog").contains(document.activeElement)'))
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
            expect(trigger).to_be_focused()
            expect(page.get_by_label('Find a transaction')).to_have_value('Cedar')
            expect(page.locator('.report-table tbody tr')).to_have_count(1)
            with page.expect_download() as export:
                page.get_by_role('link', name='Export CSV').click()
            self.assertIn('B3', Path(export.value.path()).read_text(encoding='utf-8-sig'))
            page.set_viewport_size({'width': 390, 'height': 844})
            trigger.click()
            expect(dialog).to_be_visible()
            for image in dialog.locator('img').all():
                expect(image).to_have_js_property('complete', True)
                self.assertGreater(image.evaluate('(img) => img.naturalWidth'), 0)
            self.capture(page, '03-mobile-popup.png')
            dialog.locator('.evidence-summary').scroll_into_view_if_needed()
            self.capture(page, '05-mobile-notes.png')
            self.assertLessEqual(dialog.evaluate('(el) => el.scrollWidth'), 390)
            page.get_by_role('button', name='Close evidence').click()
            self.capture(page, '04-mobile-report.png')
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
            page.get_by_label('Find a transaction').fill('')
            page.get_by_label('Support status', exact=True).select_option('No supporting')
            page.get_by_role('button', name='View evidence for B2').click()
            expect(dialog.get_by_text('No approved supporting evidence for this transaction.')).to_be_visible()
            expect(dialog.locator('.evidence-summary')).to_contain_text('Courier receipt not supplied.')
            page.keyboard.press('Escape')
            page.get_by_role('button', name='View evidence for B3').click()
            expect(dialog.get_by_text('No approved supporting evidence for this transaction.')).to_be_visible()
            page.keyboard.press('Escape')
            self.assertFalse(errors)
            browser.close()
        self.assertEqual((self.fixture.project / 'final-review/decisions.json').read_bytes(), ledger)

    def test_missing_snapshot_and_changed_evidence(self):
        """Errors remain explicit and never masquerade as approved supporting evidence."""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page()
            source = self.fixture.review.root / 'demo-receipt-1.pdf'
            source.write_bytes(b'changed evidence')
            page.goto(self.url + '/final-report')
            expect(page.locator('.report-table tbody tr').first).to_contain_text('No supporting')
            page.get_by_role('button', name='View evidence for B1').click()
            expect(page.get_by_role('dialog').get_by_text('Original evidence changed or is unavailable')).to_be_visible()
            expect(page.get_by_role('dialog').get_by_text('Evidence changed or is unavailable.', exact=False)).to_be_visible()
            page.keyboard.press('Escape')
            page.route('**/api/matching', lambda route: route.fulfill(status=400, json={'error': 'Saved matching snapshot is unavailable.'}))
            page.reload()
            expect(page.get_by_role('alert').filter(has_text='Saved matching snapshot')).to_be_visible()
            expect(page.get_by_role('link', name='Export CSV')).to_have_count(0)
            page.unroute('**/api/matching')
            page.get_by_role('button', name='Retry').click()
            expect(page.locator('.report-table tbody tr')).to_have_count(3)
            browser.close()


if __name__ == '__main__':
    unittest.main()
