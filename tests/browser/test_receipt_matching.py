"""Exercise the receipt split and combined match flow in Chromium with fixture data."""
import threading
import unittest
import json
from pathlib import Path
from tests.http_server import TestServer

from playwright.sync_api import expect, sync_playwright
from dashboard.routes import create_app
from tests.browser import browser_options
from tests.unit import test_receipt_matching as fixtures
from PIL import Image, ImageDraw
from reconciliation.duplicate_workflow import fingerprint


class ReceiptMatchingBrowserTests(unittest.TestCase):
    def test_extraction_review_accept_navigation_and_reload(self):
        """Use real local HTTP endpoints without sending documents to a model."""
        fixture = fixtures.ReceiptMatchingTests()
        fixture.setUp()
        fixture.review.manifest = {}
        fixture.review.workspace = lambda: {"name": "Fixture", "period": "December"}
        fixture.review.workflow_checks = lambda: (False, False, False)
        self.addCleanup(fixture.doCleanups)
        picture = Image.new("RGB", (480, 800), "#f5f2e9")
        drawing = ImageDraw.Draw(picture)
        for top, name, total in ((30, 'OFFICE SUPPLIES', '45.00'), (425, 'DELIVERY', '15.00')):
            drawing.rectangle((35, top, 445, top + 335), fill='white', outline='#ddd9d0', width=2)
            drawing.text((65, top + 30), 'EXAMPLE STORE', fill='#28392d', font_size=27)
            drawing.text((65, top + 85), 'RECEIPT  /  18 SEP 2026', fill='#798277', font_size=17)
            drawing.line((65, top + 130, 415, top + 130), fill='#ddd9d0', width=2)
            drawing.text((65, top + 165), name, fill='#28392d', font_size=20)
            drawing.text((65, top + 240), 'TOTAL  MYR ' + total, fill='#28392d', font_size=26)
        picture.save(fixture.source)
        digest = fingerprint(fixture.source)
        fixture.index["documents"][digest] = fixture.index["documents"].pop(fixture.digest)
        fixture.state["units"][digest + ":0"] = fixture.state["units"].pop(fixture.key)
        (fixture.work / "index.json").write_text(json.dumps(fixture.index))
        fixture.state["index_sha256"] = fingerprint(fixture.work / "index.json")
        fixture.review.data = fixture.base / "dashboard-data"
        fixture.review.data.mkdir()
        fixture.review.root = fixture.base
        fixture.review.workflow_checks = lambda: (False, False, False)
        fixture.state.update(screens={}, pairs={})
        fixture.save_state()
        server = TestServer(("127.0.0.1", 0), create_app(fixture.review, "test-token"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**browser_options(), args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/documents")
            page.get_by_role("link", name="Review receipts", exact=True).first.click()
            expect(page.locator("#receipt-pieces fieldset")).to_have_count(2)
            expect(page.locator("#original-preview img")).to_be_visible()
            expect(page.locator("#original-status")).to_have_text("Image 1")
            left = page.locator('.extraction-original').bounding_box()
            right = page.locator('.extraction-editor').bounding_box()
            self.assertLessEqual(left['x'] + left['width'], right['x'])
            self.assertAlmostEqual(left['width'] / (left['width'] + right['width']), .6, places=2)
            expect(page.locator('#receipt-pieces fieldset:visible')).to_have_count(1)
            page.get_by_role('button', name='Piece 2', exact=True).click()
            expect(page.locator('#receipt-pieces fieldset:visible [data-field="total"]')).to_have_value('15.00')
            page.get_by_role('button', name='Piece 1', exact=True).click()
            page.locator('#original-zoom').select_option('2')
            expect(page.locator('#original-preview')).to_have_css('transform', 'matrix(2, 0, 0, 2, 0, 0)')
            page.locator('#original-zoom').select_option('1')
            viewport = page.locator('#original-viewport').bounding_box()
            x, y = viewport['x'] + viewport['width'] * .55, viewport['y'] + viewport['height'] * .45
            original = page.locator('#original-preview img').bounding_box()
            page.mouse.move(x, y)
            page.mouse.wheel(0, -240)
            page.wait_for_function("Number(document.querySelector('#original-zoom').value) > 1.5")
            magnified = page.locator('#original-preview img').bounding_box()
            self.assertGreater(magnified['width'], original['width'] * 1.5)
            self.assertAlmostEqual((x - original['x']) / original['width'],
                                   (x - magnified['x']) / magnified['width'], delta=.005)
            self.assertAlmostEqual((y - original['y']) / original['height'],
                                   (y - magnified['y']) / magnified['height'], delta=.005)
            before_pan = page.locator('#original-viewport').evaluate('(el) => el.scrollLeft')
            page.mouse.down(); page.mouse.move(x - 70, y - 40, steps=5); page.mouse.up()
            self.assertGreater(page.locator('#original-viewport').evaluate('(el) => el.scrollLeft'), before_pan + 50)
            page.mouse.wheel(0, 240)
            page.wait_for_function("Number(document.querySelector('#original-zoom').value) < 1.01")
            page.locator('#original-zoom').select_option('1')
            page.locator('#add-receipt').click()
            expect(page.locator('[data-field="total"]').last).to_have_value('')
            page.get_by_role('button', name='Remove this piece from extraction').last.click()
            artifacts = Path(__file__).resolve().parents[2] / '.tools'
            artifacts.mkdir(exist_ok=True)
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(artifacts / 'extraction-review.png'), full_page=True)
            page.set_viewport_size({'width':1280, 'height':720})
            footer = page.locator('#accept-receipts').bounding_box()
            self.assertLessEqual(footer['y'] + footer['height'], 720)
            page.set_viewport_size({'width':390, 'height':844})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
            page.screenshot(path=str(artifacts / 'extraction-review-mobile.png'), full_page=True)
            page.set_viewport_size({'width':1440, 'height':1000})
            expect(page.locator('[data-field="total"]').first).to_have_value("45.00")
            expect(page.locator("#receipt-reviewer")).to_have_count(0)
            expect(page.locator('.review-header #receipt-unit')).to_be_visible()
            page.locator("#accept-receipts").click()
            expect(page.locator("#receipt-unit-status")).to_have_text("Extraction accepted.")
            page.get_by_role("link", name="Back to document status").click()
            expect(page.locator("h1")).to_have_text("Documents")
            page.get_by_role("link", name="Review receipts", exact=True).first.click()
            expect(page.locator("#receipt-unit-status")).to_have_text("Extraction accepted.")
            page.reload()
            expect(page.locator('[data-field="total"]').first).to_have_value("45.00")
            expect(page.locator("#receipt-pieces fieldset")).to_have_count(2)
            self.assertFalse(errors)
            browser.close()
