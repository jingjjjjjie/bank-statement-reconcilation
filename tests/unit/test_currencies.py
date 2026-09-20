"""Verify currency aliases without exchange conversion or evidence mutation."""
import copy
import unittest

from reconciliation.currencies import normalize_currency, normalize_currencies
from reconciliation.receipt_matching import currency
from reconciliation.matching_retrieval import retrieve
from dashboard.piece_match_jobs import validate_result


class CurrencyTests(unittest.TestCase):
    def test_aliases_and_other_codes(self):
        """Only RM changes currency identity; other codes remain allowed."""
        for raw, expected in [('RM', 'MYR'), (' rm ', 'MYR'), ('MYR', 'MYR'),
                              ('usd', 'USD'), ('SGD', 'SGD'), ('EUR', 'EUR'), ('', '')]:
            self.assertEqual(normalize_currency(raw), expected)
            if expected:
                self.assertEqual(currency(raw), expected)
        with self.assertRaises(ValueError):
            currency('')

    def test_structured_copy_preserves_amounts_source_text_and_input(self):
        """Currency fields normalize while raw wording, amount and original evidence stay intact."""
        value = {'summary': 'RM 45', 'pieces': [{'currency': 'RM', 'amount': '45.00'},
                 {'currency': 'USD', 'amount': '10.00'}], 'totals': [{'currency': 'rm', 'amount': '55.00'}]}
        before = copy.deepcopy(value)
        normalized = normalize_currencies(value)
        self.assertEqual(value, before)
        self.assertEqual(normalized['summary'], 'RM 45')
        self.assertEqual(normalized['pieces'], [{'currency': 'MYR', 'amount': '45.00'},
                                                {'currency': 'USD', 'amount': '10.00'}])
        self.assertEqual(normalized['totals'][0]['currency'], 'MYR')

    def test_retrieval_and_allocation_treat_rm_as_myr_but_not_usd(self):
        """Historical RM records remain candidates without admitting cross-currency allocation."""
        bank = {'id': 'B', 'amount': '45', 'currency': 'MYR', 'parties': ['Supplier']}
        items = [{'id': 'RM', 'amount': '45', 'currency': 'RM', 'parties': ['Supplier']},
                 {'id': 'USD', 'amount': '45', 'currency': 'USD', 'parties': ['Supplier']}]
        choices, audit = retrieve([bank], items)
        self.assertEqual(choices['B'], ['RM'])
        records = {item['id']: item for item in items}
        result = {'decisions': [{'bank_id': 'B', 'assessment': 'strong',
                  'allocations': [{'item_id': 'RM', 'amount': '45'}], 'reason': 'Same currency'}]}
        validate_result(result, ['B'], {'B': ['RM', 'USD']}, {'B': bank}, records)
        result['decisions'][0]['allocations'][0]['item_id'] = 'USD'
        with self.assertRaises(ValueError):
            validate_result(result, ['B'], {'B': ['RM', 'USD']}, {'B': bank}, records)
