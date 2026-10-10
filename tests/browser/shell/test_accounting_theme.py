"""Check the approved typography, compact navigation and preserved rainbow styling."""

import threading
import re
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
        fixture.review.completion = lambda: {'complete': False}
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
            self.assertEqual(page.locator('.brand-logo').evaluate('(e)=>getComputedStyle(e).width'), '164px')
            self.assertEqual(page.locator('.header-step.complete').first.evaluate('(e)=>getComputedStyle(e).color'), 'rgb(37, 99, 182)')
            self.assertEqual(page.locator('.brand-identity span').evaluate('(e)=>getComputedStyle(e).fontWeight'), '600')
            self.assertEqual(title.evaluate('(e)=>getComputedStyle(e).paddingBottom'), '6px')
            rainbow = page.locator('.candidate-card.suggested[data-confidence=high]').first
            expect(rainbow).to_be_visible(timeout=30000)
            self.assertIn('linear-gradient', rainbow.evaluate('(e)=>getComputedStyle(e).backgroundImage'))
            self.assertEqual(rainbow.evaluate('(e)=>getComputedStyle(e,"::before").animationName'), 'suggested-flow')
            page.emulate_media(reduced_motion='reduce')
            self.assertEqual(rainbow.evaluate('(e)=>getComputedStyle(e,"::before").animationName'), 'none')
            page.emulate_media(reduced_motion='no-preference')
            for width, height in [(2560, 1300), (1920, 950), (1536, 760), (1366, 650), (1280, 620), (1440, 1000), (1024, 900), (390, 844), (320, 740)]:
                with self.subTest(width=width):
                    page.set_viewport_size({'width': width, 'height': height})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    expect(page.get_by_role('navigation', name='Main navigation')).to_have_count(1)
                    settings = page.get_by_role('link', name='Settings', exact=True).bounding_box()
                    brand = title.bounding_box()
                    self.assertLessEqual(brand['x'] + brand['width'], settings['x'])
                    if width > 700:
                        footer = page.locator('.decision-footer').bounding_box()
                        self.assertLessEqual(footer['y'] + footer['height'], height)
                        self.assertEqual(footer['height'], 47)
                        self.assertEqual(page.locator('.evidence-panel #approve-match').count(), 1)
                        self.assertEqual(page.locator('#approve-match').bounding_box()['height'], 34)
                        if height <= 820:
                            self.assertEqual(page.locator('.decision-scroll').evaluate('(e)=>getComputedStyle(e).overflowY'), 'auto')
                            self.assertGreaterEqual(page.locator('#selected-candidates').bounding_box()['height'], rainbow.bounding_box()['height'])
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
            page.set_viewport_size({'width': 1536, 'height': 760})
            expect(page.locator('#candidate-list')).to_be_hidden()
            disclosure = page.locator('#support-group > summary')
            disclosure.focus()
            page.keyboard.press('Enter')
            expect(page.locator('#candidate-list')).to_be_visible()
            page.locator('#toggle-candidate-search').click()
            expect(page.locator('#candidate-query')).to_be_focused()
            search_box = page.locator('#candidate-query').bounding_box()
            search_button = page.locator('#toggle-candidate-search').bounding_box()
            self.assertGreaterEqual(search_box['y'], search_button['y'] + search_button['height'])
            self.assertEqual(search_box['x'], page.locator('#candidate-list').bounding_box()['x'])
            self.assertLessEqual(search_button['y'], disclosure.bounding_box()['y'] + 1)
            page.screenshot(path=str(output / 'matching-candidates-expanded.png'), full_page=True)
            for width in [390, 320]:
                page.set_viewport_size({'width': width, 'height': 760})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                bounds = page.locator('#candidate-query').bounding_box()
                self.assertGreater(bounds['width'], 140)
                page.screenshot(path=str(output / f'matching-search-inline-{width}.png'), full_page=True)
            page.set_viewport_size({'width': 1536, 'height': 760})
            page.locator('#candidate-query').press('Escape')
            disclosure.click()
            expect(page.locator('#candidate-list')).to_be_hidden()
            page.locator('#toggle-candidate-search').click()
            expect(page.locator('#candidate-query')).to_be_focused()
            expect(page.locator('#candidate-list')).to_be_visible()
            page.locator('#candidate-query').press('Escape')
            disclosure.click()
            for scale in ['0.5', '0.75', '1']:
                page.locator('#preview-zoom').select_option(scale)
                self.assertEqual(page.locator('#evidence-content').evaluate('(e)=>e.style.getPropertyValue("--preview-scale")'), scale)
            main = page.locator('.matching-main').bounding_box()
            self.assertEqual(page.locator('.queue-controls').bounding_box()['y'], main['y'])
            divider = page.get_by_role('separator', name='Resize review and evidence panels')
            expect(divider).to_be_visible()
            initial = page.locator('.decision-panel').bounding_box()['width']
            grip = divider.bounding_box()
            page.mouse.move(grip['x'] + grip['width'] / 2, grip['y'] + 80)
            page.mouse.down()
            page.mouse.move(grip['x'] + 150, grip['y'] + 80, steps=8)
            page.mouse.up()
            self.assertGreater(page.locator('.decision-panel').bounding_box()['width'], initial + 100)
            value = divider.get_attribute('aria-valuenow')
            page.reload()
            expect(divider).to_have_attribute('aria-valuenow', value)
            divider.focus()
            page.keyboard.press('Home')
            expect(divider).to_have_attribute('aria-valuenow', '50')
            page.keyboard.press('ArrowRight')
            expect(divider).to_have_attribute('aria-valuenow', '52')
            divider.dblclick()
            expect(divider).to_have_attribute('aria-valuenow', '50')
            rainbow.get_by_role('button', name='Show', exact=True).click()
            expect(rainbow).to_have_class(re.compile(r'\bpreviewing\b'))
            self.assertEqual(rainbow.evaluate('(e)=>getComputedStyle(e).outlineWidth'), '2px')
            actions = page.locator('#approve-match, #deny-match, #next-review-transaction')
            for width in [1536, 390, 320]:
                page.set_viewport_size({'width': width, 'height': 760})
                self.assertTrue(all(b['width'] <= 140 for b in [actions.nth(i).bounding_box() for i in range(3)]))
                before = actions.evaluate_all('(els)=>els.map(e=>{const b=e.getBoundingClientRect();return [b.x,b.y+scrollY,b.width,b.height]})')
                page.locator('#deny-match').click()
                expect(page.locator('#deny-match')).to_have_text('Rejected · Undo')
                expect(page.locator('#deny-match')).to_have_attribute('aria-pressed', 'true')
                page.mouse.move(0, 0)
                self.assertEqual(page.locator('#deny-match').evaluate('(e)=>getComputedStyle(e).backgroundColor'), 'rgb(179, 62, 53)')
                self.assertEqual(page.locator('#deny-match').evaluate('(e)=>getComputedStyle(e).color'), 'rgb(255, 255, 255)')
                after = actions.evaluate_all('(els)=>els.map(e=>{const b=e.getBoundingClientRect();return [b.x,b.y+scrollY,b.width,b.height]})')
                self.assertEqual(before, after)
                page.screenshot(path=str(output / f'matching-stable-undo-{width}.png'), full_page=True)
                page.locator('#deny-match').click()
                expect(page.locator('#deny-match')).to_have_text('Reject')
                expect(page.locator('#undo-match')).to_have_count(0)
                self.assertEqual(before, actions.evaluate_all('(els)=>els.map(e=>{const b=e.getBoundingClientRect();return [b.x,b.y+scrollY,b.width,b.height]})'))
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.goto(f'http://127.0.0.1:{server.server_port}/final-report')
            self.assertEqual(page.locator('.final-report').evaluate('(e)=>getComputedStyle(e).color'), 'rgb(32, 50, 71)')
            page.get_by_role('button', name='Export', exact=True).click()
            dialog = page.locator('.report-export-dialog')
            expect(dialog).to_be_visible()
            self.assertEqual(dialog.locator('.workbook-download').evaluate('(e)=>getComputedStyle(e).backgroundColor'), 'rgb(255, 255, 255)')
            self.assertEqual(dialog.locator('.button.dark').evaluate('(e)=>getComputedStyle(e).backgroundColor'), 'rgb(37, 99, 182)')
            self.assertEqual(dialog.locator('.workbook-options .button.secondary').evaluate('(e)=>getComputedStyle(e).color'), 'rgb(37, 99, 182)')
            self.assertEqual(dialog.locator('.download-word').evaluate_all('(els)=>els.map(e=>getComputedStyle(e).color)'), ['rgb(255, 255, 255)'] * 4)
            self.assertEqual(dialog.locator('.archive-download .button').evaluate_all('(els)=>els.map(e=>getComputedStyle(e).backgroundColor)'), ['rgb(37, 99, 182)'] * 4)
            self.assertEqual(page.locator('.report-heading').evaluate('(e)=>getComputedStyle(e).borderBottomWidth'), '0px')
            self.assertEqual(dialog.locator('.download-section-heading h2').evaluate_all('(els)=>els.map(e=>getComputedStyle(e).fontSize)'), ['15px', '15px'])
            self.assertEqual(dialog.locator('.archive-download .button').evaluate_all('(els)=>els.map(e=>getComputedStyle(e).minHeight)'), ['36px'] * 4)
            self.assertEqual(dialog.locator('.workbook-options .button').first.evaluate('(e)=>getComputedStyle(e).textDecorationLine'), 'none')
            for width in [1440, 390, 320]:
                page.set_viewport_size({'width': width, 'height': 1000})
                bounds = dialog.bounding_box()
                self.assertGreaterEqual(bounds['x'], 0)
                self.assertLessEqual(bounds['x'] + bounds['width'], width)
                page.screenshot(path=str(output / f'export-fixture-{width}.png'), full_page=True)
            page.keyboard.press('Escape')
            expect(dialog).to_be_hidden()
            self.assertEqual(errors, [])
            browser.close()
