"""Combined-total routing fixtures cover likely copies and ambiguous amounts."""

import unittest

from comparison_policy import combined_total, route


def unit(roles, invoice="INV-123", company="ACME"):
    """Build one extracted unit with explicit monetary roles."""
    return {"money": [{"amount": amount, "currency": currency, "role": role}
                      for amount, currency, role in roles],
            "invoice_numbers": [invoice] if invoice else [],
            "company": [company] if company else [], "dates": [],
            "brief_description": "Cleaning fee"}


class ComparisonPolicyTests(unittest.TestCase):
    def test_line_sum_matches_printed_total_across_formats(self):
        """Separate line amounts match a single photographed grand total."""
        excel = [unit([("40.00", "RM", "line_item"), ("60.00", "MYR", "line_item")])]
        photo = [unit([("100.00", "MYR", "grand_total")])]
        self.assertEqual(combined_total(excel), {"MYR": 100})
        self.assertEqual(route(excel, photo)[0], "direct_compare")

    def test_grand_total_is_not_added_to_lines(self):
        """An explicit grand total replaces its component line items."""
        document = [unit([("40", "MYR", "line_item"), ("60", "MYR", "line_item"),
                          ("100", "MYR", "grand_total")])]
        self.assertEqual(combined_total(document), {"MYR": 100})

    def test_multiple_invoice_totals_are_added(self):
        """Several invoice totals form one combined amount."""
        document = [unit([("40", "MYR", "invoice_total"), ("60", "MYR", "invoice_total")])]
        self.assertEqual(combined_total(document), {"MYR": 100})

    def test_unclear_or_different_money_uses_normal_screen(self):
        """Currency differences and conflicting totals do not take the fast route."""
        left = [unit([("100", "MYR", "grand_total")])]
        usd = [unit([("100", "USD", "grand_total")])]
        conflict = [unit([("100", "MYR", "grand_total"), ("90", "MYR", "invoice_total")])]
        missing = [unit([])]
        for right in (usd, conflict, missing):
            self.assertEqual(route(left, right)[0], "model_screen")

    def test_price_alone_does_not_fast_track(self):
        """A shared price without identity evidence stays in screening."""
        left = [unit([("100", "MYR", "grand_total")], invoice="INV-123", company="")]
        right = [unit([("100", "MYR", "grand_total")], invoice="INV-456", company="")]
        self.assertEqual(route(left, right)[0], "model_screen")

    def test_no_invoice_needs_company_and_particulars(self):
        """Company and meaningful particulars identify a same-total pair."""
        left = [unit([("100", "MYR", "grand_total")], invoice="")]
        right = [unit([("100", "MYR", "grand_total")], invoice="")]
        left[0]["dates"] = right[0]["dates"] = ["2025-12-03"]
        self.assertEqual(route(left, right)[0], "direct_compare")
        right[0]["brief_description"] = "Transport fee"
        self.assertEqual(route(left, right)[0], "model_screen")
        right[0]["brief_description"] = "Cleaning fee"
        right[0]["company"] = ["Other company"]
        self.assertEqual(route(left, right)[0], "model_screen")

    def test_one_generic_particular_word_stays_in_screening(self):
        """A shared generic word cannot take the fast route."""
        left = [unit([("100", "MYR", "grand_total")], invoice="")]
        right = [unit([("100", "MYR", "grand_total")], invoice="")]
        left[0]["brief_description"] = right[0]["brief_description"] = "Cleaning"
        self.assertEqual(route(left, right)[0], "model_screen")


if __name__ == "__main__":
    unittest.main()
