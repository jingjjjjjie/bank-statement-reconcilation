"""Fixture: Extracted pieces flowing from receipt review into Final review matching."""
import copy
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import validate

from dashboard.services import final_review, piece_matching, receipt_review
from dashboard.services.piece_match_jobs import validate_result
from reconciliation.extraction import pieces
from reconciliation.intake.duplicates import fingerprint
from tests.fixtures import receipt_review as receipt_review_fixture
from tests.unit.dashboard import test_receipt_review as fixtures


def as_model(record):
    """Project an old stored piece onto the current model output schema."""
    facts = pieces.canonical(record)
    return {'piece_type': 'Receipt or invoice', 'payer': facts['payer'], 'payee': facts['payee'], 'other_names': [],
            'amount': facts['amount'], 'amount_location': facts['amount_location'], 'currency': facts['currency'],
            'date': facts['date'], 'document_number': facts['document_number'], 'description': facts['description'],
            'references': [r for r in facts['references'] if r['type'] in ('contract', 'project', 'bank_account', 'other')]}


class PiecePipelineFixture(unittest.TestCase):
    """Reusable setUp and helpers; subclass it, or instantiate and call setUp() inside another test."""

    def setUp(self):
        """Use isolated two-receipt evidence and three bank payments."""
        self.fixture = receipt_review_fixture.ReceiptReviewFixture()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.review = self.fixture.review
        self.review.root = self.fixture.base

    def accept(self, values=None):
        """Submit exactly the current editable piece records."""
        view = receipt_review.snapshot(self.review)
        return receipt_review.accept_extraction(self.review, {'revision': view['revision'],
            'key': self.fixture.key, 'receipts': values if values is not None else view['units'][0]['receipts']})

    def decision(self, bank='B1', action='approve', allocations=None):
        """Prepare a current final-review request with an explicit human decision."""
        view = final_review.snapshot(self.review)
        return {'binding': view['binding'], 'version': view['version'], 'bank_id': bank, 'action': action,
            'allocations': allocations or [], 'reviewer': 'Test', 'note': 'Checked separate receipts', 'acknowledged': True}

