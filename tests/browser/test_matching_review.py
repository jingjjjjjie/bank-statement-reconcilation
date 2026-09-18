"""Exercise final review interactions against an isolated cache and ledger."""
import threading
import unittest
from tests.http_server import TestServer
from types import SimpleNamespace

from playwright.sync_api import sync_playwright, expect

from dashboard.routes import create_app
from tests.browser import browser_options
from dashboard import matching_review
from tests.unit import test_matching_review as fixtures


class MatchingReviewBrowserTests(unittest.TestCase):
    def test_approve_deny_undo_candidates_and_reload(self):
        """Human decisions survive reload and grouped allocations update both views."""
        fixture = fixtures.MatchingReviewTests()
        fixture.setUp()
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {"name": "Fixture", "period": "December"}
        fixture.review.workflow_checks = lambda: (False, False, False)
        suggestions = matching_review.read(fixture.cache/'decisions.json')
        suggestions[0]['assessment'] = 'strong'
        suggestions[2]['allocations'] = []
        fixture.write(fixture.cache/'decisions.json', suggestions)
        self.addCleanup(fixture.doCleanups)
        server = TestServer(('127.0.0.1',0),create_app(fixture.review,'test-token',SimpleNamespace()))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page(viewport={'width':1600,'height':1000})
            errors = []
            page.on('pageerror',lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/matching')
            expect(page.locator('.bank-row')).to_have_count(3)
            page.locator('#confidence-filter').select_option('high')
            expect(page.locator('.bank-row')).to_have_count(1)
            expect(page.locator('.bank-row')).to_contain_text('High confidence')
            expect(page.locator('.bank-row')).to_contain_text('pending')
            page.locator('#confidence-filter').select_option('low')
            expect(page.locator('.bank-row')).to_have_count(1)
            page.locator('#confidence-filter').select_option('none')
            expect(page.locator('.bank-row')).to_contain_text('No match')
            page.locator('#confidence-filter').select_option('all')
            page.get_by_role('button',name='B1 Person 1 MYR 10.00',exact=True).click()
            expect(page.locator('#matching-reviewer')).to_have_count(0)
            expect(page.locator('.candidate-card')).to_have_count(1)
            page.locator('#approve-match').click()
            expect(page.locator('#save-status')).to_contain_text('Saved')
            self.assertEqual(matching_review.snapshot(fixture.review)['banks'][0]['support_status'],'Supporting')
            page.reload()
            expect(page.locator('#save-status')).to_contain_text('Saved')
            page.get_by_role('button',name='B2 Person 2 MYR 10.00',exact=True).click()
            page.locator('#note-details summary').click()
            page.locator('#decision-note').fill('Not this receipt')
            page.locator('#deny-match').click()
            expect(page.locator('#save-status')).to_contain_text('Saved')
            self.assertEqual(matching_review.snapshot(fixture.review)['banks'][1]['review_status'],'denied')
            page.get_by_role('button',name='B1 Person 1 MYR 10.00',exact=True).click()
            page.locator('#undo-match').click()
            expect(page.locator('#save-status')).to_have_text('')
            page.locator('#candidate-picker summary').click()
            page.locator('#all-candidates').check()
            page.get_by_role('checkbox',name='Select D2 receipt-2.txt',exact=True).check()
            expect(page.locator('#approve-match')).to_be_disabled()
            page.get_by_role('textbox',name='Allocation D1',exact=True).fill('4')
            page.get_by_role('textbox',name='Allocation D2',exact=True).fill('6')
            page.locator('#decision-note').fill('Two separate expenses; remaining amounts paid separately')
            page.locator('#acknowledge').check()
            page.locator('#approve-match').click()
            expect(page.locator('#save-status')).to_contain_text('Saved')
            page.locator('#document-tab').click()
            expect(page.locator('.unmatched-row')).to_have_count(3)
            page.locator('#unmatched-bank-query').fill('Person 2')
            page.locator('#unmatched-bank').select_option('B2')
            page.locator('.unmatched-row').first.get_by_role('button').click()
            expect(page.locator('#transaction-detail')).to_contain_text('Person 2')
            self.assertFalse(errors)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),1600)
            page.set_viewport_size({'width':390,'height':844})
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
            browser.close()


if __name__=='__main__':
    unittest.main()
