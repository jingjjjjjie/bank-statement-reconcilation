"""Exercise visible money/support roles with real saved review decisions."""

import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from tests.browser import browser_options
from tests.fixtures.final_review import FinalReviewFixture
from tests.http_server import TestServer


class AllocationRoleTests(unittest.TestCase):
    def test_roles_totals_save_failure_reload_and_mobile(self):
        """Keep role edits local, save support as empty amounts, and render both widths."""
        fixture = FinalReviewFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {'name': 'Example workspace', 'period': 'December'}
        fixture.enable_review_navigation()
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'fixture', SimpleNamespace()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            base = f'http://127.0.0.1:{server.server_port}'
            page.goto(base + '/matching')
            role = page.get_by_role('combobox', name='Use as D1', exact=True)
            allocation = page.get_by_role('textbox', name='Allocation D1', exact=True)
            expect(page.locator('#selected-candidates .candidate-card')).to_have_count(1)
            page.locator('#bank-filter').select_option('all')
            expect(role).not_to_be_visible()
            page.screenshot(path=str(Path('.tools') / 'allocation-collapsed-1440.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 1000})
            expect(role).not_to_be_visible()
            expect(page.locator('#selected-candidates .show-evidence')).to_be_visible()
            page.screenshot(path=str(Path('.tools') / 'allocation-collapsed-390.png'), full_page=True)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.get_by_text('Edit allocation', exact=True).first.click()
            expect(role).to_be_visible()
            expect(role).to_have_value('money')
            allocation.fill('4.00')
            expect(page.locator('#selection-summary')).to_have_css('color', 'rgb(161, 45, 36)')
            role.select_option('support')
            expect(allocation).not_to_be_visible()
            expect(page.locator('#selection-summary')).to_contain_text('MYR 0.00 allocated')
            role.select_option('money')
            expect(allocation).to_have_value('4.00')
            allocation.fill('')
            expect(page.locator('#approve-match')).to_be_disabled()
            allocation.fill('10.00')
            page.locator('#toggle-candidate-search').click()
            page.locator('.candidate-card[data-item-id="D2"] input[type="checkbox"]').click()
            page.locator('[aria-label="Edit allocation D2"]').click()
            page.get_by_role('combobox', name='Use as D2', exact=True).select_option('support')
            expect(page.locator('#selection-summary')).to_contain_text('MYR 10.00 allocated')
            expect(page.locator('#selection-summary')).to_contain_text('equals the bank payment')
            expect(page.locator('#selection-summary')).to_have_css('color', 'rgb(36, 88, 59)')
            self.assertIn('linear-gradient', page.locator('#selection-summary').evaluate('(node) => getComputedStyle(node).backgroundImage'))
            expect(page.locator('#approve-match')).to_be_enabled()
            ledger = fixture.project / 'final-review/decisions.json'
            before = ledger.read_bytes() if ledger.exists() else None
            for width in (1440, 390):
                page.set_viewport_size({'width': width, 'height': 1000})
                expect(role).to_be_visible()
                expect(page.get_by_role('combobox', name='Use as D2', exact=True)).to_be_visible()
                expect(page.get_by_role('navigation', name='Main navigation')).to_have_count(1)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                page.get_by_role('combobox', name='Use as D2', exact=True).scroll_into_view_if_needed()
                page.screenshot(path=str(Path('.tools') / f'allocation-roles-{width}.png'), full_page=True)
            self.assertEqual(ledger.read_bytes() if ledger.exists() else None, before)
            page.route('**/api/matching-decide', lambda route: route.fulfill(status=400, json={'error': 'Synthetic save failure'}))
            page.locator('#approve-match').click()
            expect(page.locator('#save-status')).to_contain_text('not saved')
            expect(page.get_by_role('combobox', name='Use as D2', exact=True)).to_have_value('support')
            page.unroute('**/api/matching-decide')
            with page.expect_response('**/api/matching-decide') as saved:
                page.locator('#approve-match').click()
            self.assertEqual(saved.value.status, 200)
            payload = saved.value.request.post_data_json
            self.assertEqual(payload['allocations'], [{'item_id': 'D1', 'amount': '10.00'}, {'item_id': 'D2', 'amount': ''}])
            page.locator('[data-bank-id="B1"]').click()
            page.reload()
            page.locator('[aria-label="Edit allocation D2"]').click()
            page.locator('[aria-label="Edit allocation D1"]').click()
            expect(page.get_by_role('combobox', name='Use as D2', exact=True)).to_have_value('support')
            expect(page.get_by_role('combobox', name='Use as D1', exact=True)).to_have_value('money')
            page.locator('#toggle-candidate-search').click()
            page.locator('.candidate-card[data-item-id="E1"] input[type="checkbox"]').click()
            page.locator('[aria-label="Edit allocation E1"]').click()
            unknown = page.get_by_role('combobox', name='Use as E1', exact=True)
            expect(unknown).to_have_value('support')
            expect(unknown.locator('option[value="money"]')).to_have_attribute('disabled', '')
            self.assertEqual(errors, [])
            browser.close()
