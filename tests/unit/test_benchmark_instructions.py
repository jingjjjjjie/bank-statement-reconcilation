"""Check benchmark isolation and order-independent field comparisons offline."""
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.benchmark_instructions import InstructionProcess, coverage_valid, facts


class InstructionBenchmarkTests(unittest.TestCase):
    """Guard the single-variable comparison and scoring semantics."""

    def test_override_changes_only_exec_arguments(self):
        """Keep subscription login and process audit arguments unchanged."""
        calls = []

        def run(command, **kwargs):
            """Record the delegated command without launching a process."""
            calls.append((command, kwargs))

        wrapper = InstructionProcess(SimpleNamespace(run=run), Path('/tmp/minimal.txt'))
        login = ['codex', 'login', 'status']
        wrapper.run(login, timeout=30)
        original = ['codex', 'exec', '--image', '/tmp/page.png', '-']
        wrapper.run(original, input='same prompt', audit={})
        self.assertEqual(calls[0], (login, {'timeout': 30}))
        self.assertEqual(calls[1][0][:-3], original[:-1])
        self.assertEqual(calls[1][0][-1], '-')
        self.assertIn('model_instructions_file=', calls[1][0][-2])
        self.assertEqual(calls[1][1]['input'], 'same prompt')
        self.assertEqual(original, ['codex', 'exec', '--image', '/tmp/page.png', '-'])

    def test_scoring_ignores_order_but_keeps_duplicates_and_missing_values(self):
        """Do not confuse repeated or missing payable amounts with matching pieces."""
        pieces = [{'payee': ' EXAMPLE ', 'amount': '25'}, {'payee': 'Other', 'amount': ''}]
        self.assertEqual(facts(pieces, ['payee', 'amount']), facts(list(reversed(pieces)), ['payee', 'amount']))
        self.assertNotEqual(facts(pieces, ['amount']), facts(pieces + pieces, ['amount']))
        self.assertNotEqual(facts(pieces, ['amount']), facts([{'amount': '25'}, {'amount': '0'}], ['amount']))

    def test_references_preserve_type_and_leading_zeros(self):
        """Reference normalization must not erase meaningful identifier differences."""
        first = [{'references': [{'type': 'invoice', 'value': '001'}, {'type': 'other', 'value': 'A'}]}]
        second = [{'references': list(reversed(first[0]['references']))}]
        self.assertEqual(facts(first, ['references']), facts(second, ['references']))
        second[0]['references'][1] = {'type': 'invoice', 'value': '1'}
        self.assertNotEqual(facts(first, ['references']), facts(second, ['references']))

    def test_numeric_formatting_and_app_currency_alias_are_equivalent(self):
        """Do not score decimal formatting or the app's RM alias as factual errors."""
        self.assertEqual(facts([{'amount': '25.00', 'currency': 'RM'}], ['amount', 'currency']),
                         facts([{'amount': '25', 'currency': 'MYR'}], ['amount', 'currency']))

    def test_page_coverage_rejects_duplicate_or_unknown_source_units(self):
        """A schema-valid response must still bind pieces to real source pages."""
        result = {'reviewed_units': [1, 2], 'pieces': [{'source_units': [1, 2]}]}
        self.assertTrue(coverage_valid(result, 2))
        for sources in [[1, 1], [3]]:
            result['pieces'][0]['source_units'] = sources
            self.assertFalse(coverage_valid(result, 2))
