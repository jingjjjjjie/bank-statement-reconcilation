"""Protect paired benchmarking from incomplete or stale extraction evidence."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from reconciliation.extraction.pipeline.assembly import input_revision
from scripts.matching.benchmark_matching_images import extract_with_retries, extraction_coverage


class ExtractionCoverageTests(unittest.TestCase):
    """Require every source unit and current assembly before reporting completion."""

    def test_partial_document_and_excluded_input(self):
        """Partial page reads and preparation errors cannot count as completed docs."""
        index = {
            'documents': {
                'one': {'id': 'one', 'units': [{}]},
                'two': {'id': 'two', 'units': [{}, {}]},
                'bad': {'id': 'bad', 'units': [], 'error': 'unreadable input'},
                'trash': {'id': 'trash', 'units': [{}], 'accepted': False},
            }
        }
        result = extraction_coverage(index, {'units': {'one:0': {}, 'two:0': {}}})
        self.assertEqual(result['complete_documents'], 1)
        self.assertEqual(result['eligible_documents'], 3)
        self.assertEqual(result['unresolved_documents'], ['two', 'bad'])

    def test_assembly_becomes_stale_after_page_changes(self):
        """A saved assembly cannot cover changed page evidence."""
        document = {'id': 'doc', 'units': [{}, {}]}
        index = {'documents': {'doc': document}}
        state = {'units': {'doc:0': {}, 'doc:1': {}}}
        self.assertEqual(extraction_coverage(index, state)['complete_documents'], 0)
        state['assemblies'] = {'doc': {'input_revision': input_revision(document, state)}}
        self.assertEqual(extraction_coverage(index, state)['complete_documents'], 1)
        state['units']['doc:1'] = {'summary': 'changed'}
        self.assertEqual(extraction_coverage(index, state)['complete_documents'], 0)


class CapacityRetryTests(unittest.TestCase):
    """Keep capacity retries bounded and never retry unrelated failures."""

    def test_stop_after_three_capacity_failures_without_progress(self):
        """Repeated service rejection must eventually return unresolved."""
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / 'extraction').mkdir()
            events = output / 'events.jsonl'
            events.write_text('Selected model is at capacity', encoding='utf-8')

            def reject(*args):
                """Record each independent failed attempt like the real runner."""
                with (output / 'extraction/token-usage.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps({'status': 'failed', 'events': str(events)}) + '\n')
                return {'status': 'unresolved', 'unit_results': 0, 'assemblies': 0}

            with (
                patch('scripts.matching.benchmark_matching_images.extract_fresh', side_effect=reject) as run,
                patch('scripts.matching.benchmark_matching_images.time.sleep') as sleep,
            ):
                self.assertEqual(extract_with_retries(output, 1, 12)['status'], 'unresolved')
            self.assertEqual(run.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_old_capacity_error_does_not_retry_new_validation_failure(self):
        """A previous service error must not mask a later deterministic failure."""
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / 'extraction').mkdir()
            events = output / 'events.jsonl'
            events.write_text('Selected model is at capacity', encoding='utf-8')
            (output / 'extraction/token-usage.jsonl').write_text(
                json.dumps({'status': 'failed', 'events': str(events)}) + '\n', encoding='utf-8'
            )
            with patch(
                'scripts.matching.benchmark_matching_images.extract_fresh',
                return_value={'status': 'unresolved', 'unit_results': 0, 'assemblies': 0},
            ) as run:
                extract_with_retries(output, 1, 12)
            self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
