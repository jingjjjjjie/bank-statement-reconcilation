"""Check statement year validation before sending extraction requests."""
import threading
import unittest
from playwright.sync_api import sync_playwright, expect
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
                route.fulfill(json={'existing': False})
                return
            data = {'session': {'active': True, 'review_id': 'fixture', 'token': 'fixture'},
                'workspace': {'name': 'Fixture', 'period': ''}, 'workflow-checks': {'steps': []},
                'development-mode': {'enabled': False}, 'bank-statement': {'available': False},
                'source': {'active': '/fixture/documents', 'selected': {'path': '/fixture/documents'},
                    'bank': {'path': '/fixture/statement.pdf'}}}.get(path, {})
            route.fulfill(json=data)
        with sync_playwright() as p:
            browser = p.chromium.launch(**browser_options())
            page = browser.new_page()
            page.route('**/api/**', respond)
            page.goto(f'http://127.0.0.1:{server.server_port}/bank')
            page.locator('#prepare-bank').click()
            expect(page.locator('#bank-error')).to_contain_text('Enter the statement year')
            self.assertEqual(requests, [])
            page.locator('#bank-year').fill('2025.5')
            page.locator('#prepare-bank').click()
            self.assertEqual(requests, [])
            page.locator('#bank-year').fill('2025')
            page.locator('#prepare-bank').click()
            expect(page.locator('#prepare-bank')).to_be_enabled()
            self.assertEqual(requests, [{'year': 2025}])
            browser.close()
