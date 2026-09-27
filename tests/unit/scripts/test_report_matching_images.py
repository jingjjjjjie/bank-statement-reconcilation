"""Verify paired monetary comparisons and incomplete usage reporting."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.report_matching_images import aggregate, allocation_key


class MatchingReportTests(unittest.TestCase):
    """Avoid reporting formatting differences or missing usage as measured savings."""

    def test_decimal_formatting_and_allocation_order(self):
        """Equivalent allocation values compare equal while blank stays unknown."""
        left = {'decision': {'allocations': [{'item_id': 'a', 'amount': '100.00'},
                                            {'item_id': 'b', 'amount': ''}]}}
        right = {'decision': {'allocations': [{'item_id': 'b', 'amount': ''},
                                             {'item_id': 'a', 'amount': '100'}]}}
        self.assertEqual(allocation_key(left), allocation_key(right))
        right['decision']['allocations'][0]['amount'] = '0'
        self.assertNotEqual(allocation_key(left), allocation_key(right))

    def test_known_cost_keeps_unknown_attempt_visible(self):
        """Count a completed attempt once and include cache-write pricing exactly."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            usage = {'input_tokens': 1000, 'cached_input_tokens': 200,
                     'output_tokens': 100, 'reasoning_output_tokens': 50}
            raw = root / 'events.jsonl'
            raw.write_text(json.dumps({'type': 'turn.completed',
                'usage': {**usage, 'cache_write_input_tokens': 100}}) + '\n', encoding='utf-8')
            events = [{'id': 'a', 'status': 'started'},
                      {'id': 'a', 'status': 'finished', 'usage': usage, 'events': str(raw)},
                      {'id': 'b', 'status': 'failed', 'usage': None},
                      {'status': 'cached'}]
            audit = root / 'usage.jsonl'
            audit.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
            result = aggregate([audit])
            self.assertEqual(result['attempts'], 2)
            self.assertEqual(result['cache_hits'], 1)
            self.assertEqual(result['unknown_attempts'], 1)
            self.assertEqual(result['priced_attempts'], 1)
            self.assertFalse(result['api_equivalent_complete'])
            self.assertEqual(result['totals']['input_tokens'], 1000)
            self.assertAlmostEqual(result['api_equivalent_usd_known'], .00538)


if __name__ == '__main__':
    unittest.main()
