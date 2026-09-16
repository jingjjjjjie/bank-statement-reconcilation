"""Local field triggers should catch cross-format copies without amount-only matches."""

import unittest

from similarity import score


class SimilarityTests(unittest.TestCase):
    def test_excel_and_photo_fields_trigger_review(self):
        """Punctuation and missing fields do not hide a likely copy."""
        excel = [{"invoice_numbers": ["INV-123"], "company": ["ACME Sdn. Bhd."],
                  "amounts_and_currencies": ["MYR 100.00"], "brief_description": "Cleaning fee"}]
        photo = [{"invoice_numbers": ["INV 123"], "company": ["ACME SDN BHD"],
                  "amounts_and_currencies": [], "brief_description": "Cleaning"}]
        percent, matched = score(excel, photo)
        self.assertGreaterEqual(percent, 70)
        self.assertIn("invoice", matched)
        self.assertIn("company", matched)

    def test_amount_alone_does_not_trigger_review(self):
        """A shared amount needs another independent match."""
        left = [{"amounts_and_currencies": ["MYR 100"]}]
        right = [{"amounts_and_currencies": ["MYR 100"]}]
        self.assertEqual(score(left, right)[0], 0)

    def test_different_invoice_does_not_reach_threshold(self):
        """A conflicting invoice number outweighs shared company and amount."""
        left = [{"invoice_numbers": ["INV-123"], "company": ["ACME"],
                 "amounts_and_currencies": ["MYR 100"]}]
        right = [{"invoice_numbers": ["INV-456"], "company": ["ACME"],
                  "amounts_and_currencies": ["MYR 100"]}]
        self.assertLess(score(left, right)[0], 70)


if __name__ == "__main__":
    unittest.main()
