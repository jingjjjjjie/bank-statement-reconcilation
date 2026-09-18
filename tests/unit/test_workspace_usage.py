"""Check cumulative accounting across projects, benchmarks and copied logs."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from reconciliation.token_usage import record
from reconciliation.workspace_usage import workspace_summary


class WorkspaceUsageTests(unittest.TestCase):
    def test_import_deduplicates_and_survives_removed_logs(self):
        """Copied histories do not multiply attempts or downgrade known usage."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            usage = dict(input_tokens=100, cached_input_tokens=40, output_tokens=20, reasoning_output_tokens=5)
            finished = {'id': 'one', 'status': 'finished', 'stage': 'pdf', 'model': 'sol', 'usage': usage}
            entries = [finished, {'id': 'two', 'status': 'started'},
                       {'status': 'cached', 'event_id': 'cache-one', 'usage': {k: 0 for k in usage}}]
            paths = []
            for name, data in [('projects/a/review', entries), ('benchmarks/b', [finished]),
                               ('development-cache/runs/a', entries),
                               ('projects/a/history', [{'id': 'one', 'status': 'started'}])]:
                path = root / name / 'token-usage.jsonl'
                path.parent.mkdir(parents=True)
                path.write_text('\n'.join(json.dumps(e) for e in data), encoding='utf-8')
                paths.append(path)
            result = workspace_summary(root)
            self.assertEqual(result['totals'], usage)
            self.assertEqual((result['attempts'], result['unknown_attempts'], result['cache_hits']), (2, 1, 1))
            self.assertFalse(result['complete'])
            for path in paths:
                path.unlink()
            self.assertEqual(workspace_summary(root), result)

    def test_parallel_live_records_are_accumulated_once(self):
        """New records persist centrally without relying on development cache."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def write(number):
                """Represent independent concurrent workflow processes."""
                record(root / str(number) / 'token-usage.jsonl', {
                    'id': str(number), 'status': 'finished', 'stage': 'pdf',
                    'usage': dict(input_tokens=10, cached_input_tokens=0, output_tokens=2, reasoning_output_tokens=0)})
            with patch('reconciliation.workspace_usage.WORKSPACE', root):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(write, range(12)))
            result = workspace_summary(root)
            self.assertEqual(result['attempts'], 12)
            self.assertEqual(result['totals']['input_tokens'], 120)
            self.assertTrue(result['complete'])

    def test_partial_log_is_not_presented_as_complete(self):
        """An interrupted write stays visibly incomplete until it is repaired."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'token-usage.jsonl'
            path.write_text('{"id":', encoding='utf-8')
            self.assertFalse(workspace_summary(root)['complete'])
            path.write_text('', encoding='utf-8')
            self.assertTrue(workspace_summary(root)['complete'])
