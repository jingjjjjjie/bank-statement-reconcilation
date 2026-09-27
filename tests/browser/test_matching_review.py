"""Review one bank transaction against several supporting candidates in Playwright."""
from pathlib import Path
import threading
import unittest
from types import SimpleNamespace

from playwright.sync_api import sync_playwright, expect
from dashboard.routes import create_app
from dashboard import matching_review
from tests.browser import browser_options
from tests.http_server import TestServer
from tests.unit import test_matching_review as fixtures


class MatchingReviewBrowserTests(unittest.TestCase):
    def test_filters_change_open_payment_and_empty_state(self):
        """Keep the displayed payment, queue and reload inside both filters."""
        fixture = fixtures.MatchingReviewTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {'name': 'Fixture', 'period': 'December'}
        fixture.review.workflow_checks = lambda: (False, False, False)
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test-token', SimpleNamespace()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page()
            base = f'http://127.0.0.1:{server.server_port}'
            page.goto(base + '/matching')
            expect(page.locator('.transaction-number[aria-current]')).to_be_visible(timeout=30000)
            banks = page.request.get(base + '/api/matching').json()['banks']
            for confidence in ['high', 'low', 'none', 'all']:
                for decision in ['all', 'pending', 'approved', 'denied']:
                    page.locator('#confidence-filter').select_option(confidence)
                    page.locator('#bank-filter').select_option(decision)
                    expected = [bank for bank in banks
                                if (confidence == 'all' or (bank['confidence'].get('level') or 'none') == confidence)
                                and (decision == 'all' or bank['review_status'] == decision)]
                    expect(page.locator('#queue-count')).to_have_text(f'{len(expected)} transactions')
                    if expected:
                        current = page.locator('.transaction-number[aria-current]').get_attribute('data-bank-id')
                        self.assertIn(current, [bank['id'] for bank in expected])
                        expect(page.locator('#bank-view')).to_be_visible()
                    else:
                        expect(page.locator('#bank-view')).to_be_hidden()
                        expect(page.locator('#filtered-empty')).to_be_visible()
                        expect(page.locator('.transaction-title')).to_have_count(0)
            page.reload()
            expect(page.locator('#filtered-empty')).to_be_visible(timeout=30000)
            browser.close()

    def test_compare_candidates_then_save_transaction(self):
        """Candidate paging and preview never change the bank or approve evidence."""
        fixture = fixtures.MatchingReviewTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {'name': 'Fixture', 'period': 'December'}
        fixture.review.workflow_checks = lambda: (False, False, False)
        facts = matching_review.read(fixture.cache / 'facts.json')
        master = fixture.project / 'bank-output/master_statement.csv'
        with master.open('a', encoding='utf-8', newline='') as stream:
            for number in range(4, 14):
                stream.write(f'{number},{fixture.root / "statement.txt"},1,passed\n')
        facts['bank_hash'] = fixtures.fingerprint(master)
        facts['banks'].extend(dict(facts['banks'][2], id=f'B{i}') for i in range(4, 14))
        facts['items'].extend(dict(facts['items'][1], id=f'D{i}', parties=[f'Candidate {i}']) for i in range(3, 9))
        fixture.write(fixture.cache / 'facts.json', facts)
        (fixture.cache / 'matching').mkdir()
        fixture.write(fixture.cache / 'matching/input-candidates.json', {'banks': [
            {'id': f'B{i}', 'candidate_ids': [f'D{j}' for j in range(1, 9)]} for i in range(1, 14)]})
        suggestions = matching_review.read(fixture.cache / 'decisions.json')
        suggestions[0]['assessment'] = 'strong'
        suggestions[2]['allocations'] = []
        suggestions.extend(dict(suggestions[2], bank_id=f'B{i}') for i in range(4, 14))
        fixture.write(fixture.cache / 'decisions.json', suggestions)
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test-token', SimpleNamespace()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        screenshots = Path('duplicated/inspection/supporting-candidates')
        screenshots.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page(viewport={'width': 1440, 'height': 960})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/matching')
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B1')
            expect(page.locator('.transaction-title')).to_have_count(1)
            expect(page.locator('#candidate-search')).not_to_be_visible()
            expect(page.locator('#all-candidates')).to_have_count(0)
            page.locator('#toggle-candidate-search').click()
            expect(page.locator('#candidate-query')).to_be_focused()
            page.locator('#candidate-query').press('Escape')
            expect(page.locator('#candidate-search')).not_to_be_visible()
            expect(page.locator('#toggle-candidate-search')).to_be_focused()
            expect(page.locator('.payment-description')).to_be_visible()
            expect(page.locator('.payment-description')).to_have_text('Payment')
            expect(page.locator('.transaction-direction')).to_have_text('Pay to')
            expect(page.get_by_text('Payment details', exact=True)).to_have_count(0)
            expect(page.locator('.review-state')).to_have_text('Awaiting review')
            expect(page.locator('#transaction-detail').get_by_text('Why suggested', exact=True)).to_have_count(0)
            expect(page.locator('#selected-candidates .candidate-card')).to_have_count(1)
            page.get_by_role('button', name='Remove D1 from selected', exact=True).click()
            expect(page.locator('#selected-candidates .candidate-card')).to_have_count(0)
            expect(page.locator('#approve-match')).to_be_disabled()
            page.get_by_role('checkbox', name='Select D1 receipt-1.txt', exact=True).click()
            expect(page.locator('#selected-candidates .candidate-card')).to_have_count(1)
            expect(page.locator('#candidate-list [data-item-id="D1"]')).to_have_count(0)
            expect(page.locator('.candidate-card.suggested')).to_have_count(1)
            suggested = page.locator('.candidate-card.suggested')
            expect(suggested.locator('.suggested-label')).to_be_visible()
            suggested.locator('.candidate-summary').click()
            expect(suggested.get_by_role('region', name='Why suggested')).to_be_visible()
            expect(suggested.get_by_role('region', name='Why suggested')).to_contain_text('Possible supporting document')
            suggested.locator('.candidate-summary').click()
            expect(page.locator('.transaction-number')).to_have_count(10)
            page.locator('#next-transactions').click()
            expect(page.locator('.transaction-number')).to_have_count(3)
            expect(page.locator('.transaction-number').first).to_have_text('11')
            expect(page.locator('#next-transactions')).to_be_disabled()
            page.locator('#previous-transactions').click()
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B1')
            expect(page.get_by_text('Add a note', exact=True)).to_have_count(0)
            expect(page.locator('#decision-note')).to_have_count(0)
            expect(page.get_by_text('Decision history', exact=True)).to_have_count(0)
            expect(page.locator('#acknowledge')).to_have_count(0)
            expect(page.locator('#candidate-list .candidate-card')).to_have_count(5)
            expect(page.locator('#candidate-count')).to_have_text('1\u20135 of 7 candidates')
            expect(page.locator('.proposal-card')).to_have_count(0)
            for card in page.locator('.candidate-card').all():
                self.assertLess(card.bounding_box()['height'], 70)
                expect(card).to_be_in_viewport(ratio=1)
            left = page.locator('.decision-panel').bounding_box()
            right = page.locator('.evidence-panel').bounding_box()
            self.assertAlmostEqual(left['width'], right['width'], delta=1)
            expect(page.locator('#evidence-content')).to_contain_text('Original receipt 1')
            page.screenshot(path=str(screenshots / '01-five-candidates.png'), full_page=True)
            page.locator('#candidate-next').click()
            expect(page.locator('#candidate-count')).to_have_text('6\u20137 of 7 candidates')
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B1')
            expect(page.locator('.transaction-title')).to_have_text('Person 1')
            page.locator('#candidate-prev').click()
            candidate = page.get_by_role('article', name='Candidate D2', exact=True)
            candidate.locator('.candidate-summary').click()
            expect(page.locator('#evidence-content')).to_contain_text('Original receipt 2')
            expect(candidate.get_by_role('checkbox')).not_to_be_checked()
            expect(page.locator('#selected-candidates [data-item-id="D1"]')).to_be_visible()
            self.assertFalse((fixture.project / 'final-review/decisions.json').exists())
            page.screenshot(path=str(screenshots / '02-inspect-alternative.png'), full_page=True)
            candidate.locator('.candidate-summary').click()
            candidate.locator('.candidate-summary').focus()
            page.keyboard.press('Enter')
            expect(candidate.locator('.candidate-details')).to_have_attribute('open', '')
            candidate.get_by_role('button', name='Use only this', exact=True).click()
            expect(page.locator('#selected-candidates [data-item-id="D2"]')).to_be_visible()
            expect(page.get_by_role('checkbox', name='Select D1 receipt-1.txt', exact=True)).not_to_be_checked()
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B1')
            page.once('dialog', lambda dialog: dialog.dismiss())
            page.locator('[data-bank-id="B2"]').click()
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B1')
            page.locator('#approve-match').click()
            expect(page.locator('#save-status')).to_contain_text('Saved')
            saved = matching_review.snapshot(fixture.review)['banks'][0]
            self.assertEqual(saved['decision']['allocations'][0]['item_id'], 'D2')
            self.assertEqual(saved['support_status'], 'Supporting')
            expect(page.locator('[data-bank-id="B1"]')).to_have_class('transaction-number finished')
            page.reload()
            expect(page.locator('#save-status')).to_contain_text('Saved')
            expect(page.locator('#selected-candidates [data-item-id="D2"]')).to_be_visible()
            page.locator('#undo-match').click()
            expect(page.locator('#save-status')).to_have_text('')
            page.locator('#bank-filter').select_option('pending')
            page.locator('#confidence-filter').select_option('high')
            expect(page.locator('.transaction-number')).to_have_count(1)
            page.locator('#confidence-filter').select_option('all')
            page.locator('[data-bank-id="B2"]').click()
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B2')
            page.locator('#deny-match').click()
            expect(page.locator('#save-status')).to_contain_text('Saved')
            self.assertEqual(matching_review.snapshot(fixture.review)['banks'][1]['review_status'], 'denied')
            page.locator('#bank-filter').select_option('all')
            page.locator('[data-bank-id="B1"]').click()
            page.get_by_role('checkbox', name='Select D2 receipt-2.txt', exact=True).click()
            expect(page.locator('#approve-match')).to_be_disabled()
            expect(page.locator('#selection-summary')).to_have_css('color', 'rgb(161, 45, 36)')
            for item, value in [('D1', '4'), ('D2', '6')]:
                card = page.get_by_role('article', name=f'Candidate {item}', exact=True)
                card.locator('.candidate-summary').click()
                card.get_by_role('textbox', name=f'Allocation {item}', exact=True).fill(value)
            page.locator('#approve-match').click()
            expect(page.locator('#save-status')).to_contain_text('Saved')
            page.locator('[data-bank-id="B3"]').click()
            expect(page.locator('#approve-match')).to_be_disabled()
            expect(page.locator('#candidate-list .candidate-card')).to_have_count(5)
            page.locator('#toggle-candidate-search').click()
            page.locator('#candidate-query').fill('E1')
            expect(page.locator('.candidate-card')).to_have_count(1)
            page.get_by_role('checkbox', name='Select E1 receipt-2.txt', exact=True).click()
            page.locator('#approve-match').click()
            expect(page.locator('#save-status')).to_contain_text('Saved')
            self.assertEqual(matching_review.snapshot(fixture.review)['banks'][2]['support_status'], 'No supporting')
            page.locator('#undo-match').click()
            expect(page.locator('#save-status')).to_have_text('')
            page.get_by_role('button', name='Review options').click()
            page.locator('#document-tab').click()
            expect(page.locator('#document-view')).to_be_visible()
            page.locator('#unmatched-bank-query').fill('Person 2')
            page.locator('#unmatched-bank').select_option('B2')
            page.locator('.unmatched-row').first.get_by_role('button').click()
            expect(page.locator('.transaction-number[aria-current]')).to_have_attribute('data-bank-id', 'B2')
            page.locator('[data-bank-id="B1"]').click()
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.get_by_role('button', name='How to use this page')).to_have_count(1)
            page.get_by_role('button', name='How to use this page').click()
            expect(page.get_by_role('tooltip')).to_be_visible()
            page.keyboard.press('Escape')
            page.mouse.move(380, 840)
            expect(page.get_by_role('tooltip')).not_to_be_visible()
            expect(page.get_by_role('navigation')).to_have_count(1)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
            page.screenshot(path=str(screenshots / '03-mobile.png'), full_page=True)
            self.assertFalse(errors)
            browser.close()


if __name__ == '__main__':
    unittest.main()
