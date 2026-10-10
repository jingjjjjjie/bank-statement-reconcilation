"""Check the approved typography, compact navigation and preserved rainbow styling."""

import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import expect, sync_playwright

from dashboard.routes import create_app
from dashboard.services.matching import final_review
from tests.browser import browser_options
from tests.fixtures.final_review import FinalReviewFixture
from tests.http_server import TestServer


class AccountingThemeTests(unittest.TestCase):
    """Exercise real rendered controls without using customer data or model calls."""

    def test_brand_navigation_and_rainbow(self):
        """Keep fonts, responsive chrome, help and confidence effects intact."""
        fixture = FinalReviewFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {'name': 'Fixture', 'period': 'December'}
        fixture.enable_review_navigation()
        proposals = final_review.read(fixture.cache / 'decisions.json')
        proposals[0]['assessment'] = 'strong'
        fixture.write(fixture.cache / 'decisions.json', proposals)
        server = TestServer(('127.0.0.1', 0), create_app(fixture.review, 'test-token', SimpleNamespace()))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        output = Path('duplicated/inspection/accounting-copilot')
        output.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options())
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/matching')
            title = page.locator('.brand-identity strong')
            expect(title).to_have_text('Accounting Copilot')
            page.evaluate("document.fonts.load('800 17px Syne')")
            typography = title.evaluate('''e => {
                const s=getComputedStyle(e);
                return [s.fontFamily,s.fontWeight,s.fontSize,s.letterSpacing,s.backgroundImage];
            }''')
            self.assertEqual(typography[:4], ['Syne, sans-serif', '800', '17px', '-0.34px'])
            self.assertIn('oklch(0.52 0.18 250)', typography[4])
            self.assertIn('oklch(0.55 0.18 210)', typography[4])
            self.assertTrue(page.locator('.brand-logo').evaluate('(e)=>e.complete && e.naturalWidth>0'))
            rainbow = page.locator('.candidate-card.suggested[data-confidence=high]').first
            expect(rainbow).to_be_visible(timeout=30000)
            self.assertIn('linear-gradient', rainbow.evaluate('(e)=>getComputedStyle(e).backgroundImage'))
            self.assertEqual(rainbow.evaluate('(e)=>getComputedStyle(e,"::before").animationName'), 'suggested-flow')
            page.emulate_media(reduced_motion='reduce')
            self.assertEqual(rainbow.evaluate('(e)=>getComputedStyle(e,"::before").animationName'), 'none')
            page.emulate_media(reduced_motion='no-preference')
            for width, height in [(1440, 1000), (1024, 900), (390, 844), (320, 740)]:
                with self.subTest(width=width):
                    page.set_viewport_size({'width': width, 'height': height})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    expect(page.get_by_role('navigation', name='Main navigation')).to_have_count(1)
                    settings = page.get_by_role('link', name='Settings', exact=True).bounding_box()
                    brand = title.bounding_box()
                    self.assertLessEqual(brand['x'] + brand['width'], settings['x'])
                    active = page.locator('.header-link.active')
                    self.assertEqual(active.evaluate('(e)=>getComputedStyle(e).height'), '44px')
                    button = page.get_by_role('button', name='How to use this page')
                    expect(button).to_have_count(1)
                    button.click()
                    expect(page.locator('.page-help-panel')).to_be_visible()
                    page.keyboard.press('Escape')
                    expect(page.locator('.page-help-panel')).to_be_hidden()
                    page.mouse.move(0, 0)
                    button.evaluate('(e)=>e.blur()')
                    page.screenshot(path=str(output / f'matching-fixture-{width}.png'), full_page=True)
            self.assertEqual(errors, [])
            browser.close()
