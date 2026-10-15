"""Check statement year validation before sending extraction requests."""

import threading
import unittest

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from tests.browser import browser_options
from tests.http_server import TestServer


class BankYearTests(unittest.TestCase):
    def test_empty_year_does_not_submit_and_valid_year_is_integer(self):
        """Placeholder text cannot be submitted as a year or trigger extraction."""
        server = TestServer(('127.0.0.1', 0), create_app(token='fixture'))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        requests = []

        def respond(route):
            """Provide isolated bank-page responses without processing real inputs."""
            path = route.request.url.split('/api/')[1]
            if path == 'source/bank-prepare':
                requests.append(route.request.post_data_json)
                if route.request.post_data_json['bank'] == 'cimb':
                    route.fulfill(
                        status=400,
                        json={'error': 'Selected CIMB, but this PDF is a Maybank statement. Select Maybank.'},
                    )
                    return
                route.fulfill(json={'existing': False})
                return
            data = {
                'session': {'active': True, 'review_id': 'fixture', 'token': 'fixture'},
                'workspace': {'name': 'Fixture', 'period': ''},
                'workflow-checks': {'steps': []},
                'development-mode': {'enabled': False},
                'bank-statement': {'available': False},
                'source': {
                    'active': '/fixture/documents',
                    'selected': {'path': '/fixture/documents'},
                    'bank': {'path': '/fixture/statement.pdf'},
                },
            }.get(path, {})
            route.fulfill(json=data)

        with sync_playwright() as p:
            browser = p.chromium.launch(**browser_options())
            page = browser.new_page()
            page.route('**/api/**', respond)
            page.goto(f'http://127.0.0.1:{server.server_port}/bank')
            page.locator('#prepare-bank').click()
            expect(page.locator('#bank-error')).to_contain_text('Choose the bank')
            self.assertEqual(requests, [])
            page.locator('#bank-format').select_option('maybank')
            page.locator('#prepare-bank').click()
            expect(page.locator('#bank-error')).to_contain_text('Enter the statement year')
            self.assertEqual(requests, [])
            page.locator('#bank-year').fill('2025.5')
            page.locator('#prepare-bank').click()
            self.assertEqual(requests, [])
            page.locator('#bank-year').fill('2025')
            page.locator('#prepare-bank').click()
            expect(page.locator('#prepare-bank')).to_be_enabled()
            self.assertEqual(requests, [{'year': 2025, 'bank': 'maybank'}])
            for width in (1280, 390):
                page.set_viewport_size({'width': width, 'height': 844})
                expect(page.locator('.page-help-button')).to_have_count(1)
                expect(page.get_by_role('navigation', name='Main navigation')).to_have_count(1)
                expect(page.locator('#bank-format')).to_be_visible()
                page.locator('.page-help-button').focus()
                expect(page.locator('[role="tooltip"]')).to_contain_text('Wrong-bank selections')
                page.keyboard.press('Escape')
                expect(page.locator('[role="tooltip"]')).to_be_hidden()
                self.assertTrue(
                    page.locator('#bank-format').evaluate('(el) => el.getBoundingClientRect().right <= innerWidth')
                )
            page.locator('#bank-format').select_option('cimb')
            page.locator('#prepare-bank').click()
            expect(page.locator('#bank-error')).to_contain_text('Selected CIMB')
            expect(page.locator('#prepare-bank')).to_be_enabled()
            expect(page.locator('#bank-format')).to_have_value('cimb')
            page.route(
                '**/api/bank-statement',
                lambda route: route.fulfill(
                    json={
                        'available': True,
                        'bank': 'uob',
                        'account': '123',
                        'currency': 'MYR',
                        'opening_balance': '100.00',
                        'closing_balance': '105.00',
                        'opening_balance_origin': 'inferred',
                        'total_money_in': '5.00',
                        'total_money_out': '0.00',
                        'count': 1,
                        'matched': 0,
                        'balance_checks': 'passed',
                        'validation_note': 'Filtered account-activity export; full-period completeness is not verified.',
                        'transactions': [
                            {
                                'date': '2025-01-01',
                                'page': 1,
                                'counterparty': '',
                                'narration': 'Example',
                                'money_in': '5.00',
                                'money_out': '0.00',
                                'balance': '105.00',
                            }
                        ],
                    }
                ),
            )
            page.locator('#bank-format').select_option('uob')
            page.locator('#prepare-bank').click()
            expect(page.locator('#bank-validation-note')).to_contain_text('completeness is not verified')
            expect(page.locator('#bank-opening')).to_have_text('100.00 (inferred)')
            expect(page.locator('#bank-account')).to_contain_text('UOB')
            browser.close()
