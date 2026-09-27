"""Fixture: A frozen Final review snapshot with bank lines, supporting items and a decision ledger."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dashboard.services import final_review as matching
from reconciliation.intake.duplicates import fingerprint


class FinalReviewFixture(unittest.TestCase):
    """Reusable setUp and helpers; subclass it, or instantiate and call setUp() inside another test."""

    def setUp(self):
        """Build an isolated cache, bank master and original evidence corpus."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'duplicated/projects/test'
        self.project.mkdir(parents=True)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.review = SimpleNamespace(
            manifest_path=self.project / 'manifest.json',
            root=self.root / 'uploads/documents',
            data=self.project / 'data',
        )
        self.review.root.mkdir(parents=True)
        original = self.root / 'statement.txt'
        original.write_text('Original statement', encoding='utf-8')
        master = self.project / 'bank-output/master_statement.csv'
        master.parent.mkdir()
        with master.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['sequence', 'source', 'page', 'balance_checks'])
            writer.writeheader()
            writer.writerows(
                {'sequence': n, 'source': str(original), 'page': 1, 'balance_checks': 'passed'} for n in (1, 2, 3)
            )
        documents = {}
        for n in (1, 2):
            source = self.review.root / f'receipt-{n}.txt'
            source.write_text(f'Original receipt {n} amount 10', encoding='utf-8')
            documents[fingerprint(source)] = {
                'paths': [str(source)],
                'units': [{'label': 'Page 1', 'text': source.read_text()}],
            }
        digests = list(documents)
        banks = [
            {
                'id': f'B{n}',
                'transaction_id': f'tx-{n}',
                'amount': '10' if n < 3 else '5',
                'currency': 'MYR',
                'direction': 'out',
                'date': '2025-12-01',
                'parties': [f'Person {n}'],
                'description': 'Payment',
                'references': [],
            }
            for n in (1, 2, 3)
        ]
        items = [
            {
                'id': f'D{n}',
                'document': digests[n - 1],
                'amount': '10',
                'currency': 'MYR',
                'parties': [f'Person {n}'],
                'description': 'Receipt',
                'location': 'Page 1',
                'unit': 0,
                'source_cells': [],
                'boundary_unresolved': False,
            }
            for n in (1, 2)
        ]
        items.append({**items[1], 'id': 'E1', 'amount': '', 'currency': ''})
        self.write(
            self.cache / 'facts.json',
            {
                'banks': banks,
                'items': items,
                'statement_hash': fingerprint(original),
                'bank_hash': fingerprint(master),
                'assembly_count': 1,
            },
        )
        self.write(self.cache / 'index.json', {'manifest': str(self.review.manifest_path), 'documents': documents})
        self.write(
            self.cache / 'decisions.json',
            [
                {
                    'bank_id': f'B{n}',
                    'assessment': 'tentative',
                    'allocations': [{'item_id': 'D1', 'amount': '10'}],
                    'reason': 'Possible supporting document',
                }
                for n in (1, 2, 3)
            ],
        )
        self.addCleanup(patch.stopall)
        patch.object(matching, 'WORKSPACE', self.root).start()
        patch.object(matching, 'CACHE', self.cache).start()

    def write(self, path, data):
        """Write fixture JSON to an isolated location."""
        path.write_text(json.dumps(data), encoding='utf-8')

    def request(self, bank='B1', action='approve', allocations=None, **extra):
        """Build a request bound to the current persisted revision."""
        state = matching.context(self.review)[1]
        return {
            'bank_id': bank,
            'action': action,
            'binding': state['binding'],
            'version': state['version'],
            'allocations': allocations if allocations is not None else [{'item_id': 'D1', 'amount': '10'}],
            'reviewer': 'Test reviewer',
            'note': 'Checked originals',
            'acknowledged': True,
            **extra,
        }
