"""Check receipt particulars use available facts without invented placeholders."""

import unittest

from dashboard.services.matching.particulars import confirmed_particular, particular


class ParticularTests(unittest.TestCase):
    def test_format_and_missing_fields(self):
        """Use real values in order and omit unavailable fields and labels."""
        self.assertEqual(particular({'document_number': 'R-001', 'payee': 'Example Sdn. Bhd.',
                                     'description': 'Office supplies', 'amount': '1200.5'}),
                         'RECEIPT NO R-001 : Example Sdn. Bhd. : Office supplies : 1,200.50')
        self.assertEqual(particular({'description': 'Taxi', 'amount': '0'}), 'Taxi : 0.00')
        self.assertEqual(particular({'parties': ['Unknown role'], 'amount': None}), '')
        self.assertEqual(particular({'invoice_numbers': ['123'], 'amount': 'invalid'}), 'RECEIPT NO 123')

    def test_each_confirmed_receipt_has_its_own_line(self):
        """Pending, denied and stale selections never populate PARTICULAR."""
        items = {'a': {'document_number': '1'}, 'b': {'payee': 'Vendor', 'amount': '3'}}
        bank = {'review_status': 'approved', 'stale': False,
                'decision': {'allocations': [{'item_id': 'a'}, {'item_id': 'b'}]}}
        self.assertEqual(confirmed_particular(bank, items), 'RECEIPT NO 1\nVendor : 3.00')
        for status, stale in [('pending', False), ('denied', False), ('approved', True)]:
            self.assertEqual(confirmed_particular({**bank, 'review_status': status, 'stale': stale}, items), '')
