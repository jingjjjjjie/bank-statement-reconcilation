"""Fixture: Multi-page PDF reviews with a page-counting fake model."""
import json
import tempfile
import unittest
from pathlib import Path

import pymupdf
from jsonschema import validate

from reconciliation.core.settings import DEFAULTS
from reconciliation.extraction import pieces, workflow
from reconciliation.intake.duplicates import organize


class Reviewer:
    """Return validated source-bound pieces while counting actual workflow requests."""
    model = 'fixture'

    def __init__(self, pages):
        """Describe one invoice spanning every supplied page."""
        self.pages, self.calls, self.invalid, self.fail = pages, [], False, False
        self.fail_at, self.renumber = None, False

    def ask(self, prompt, schema, images=()):
        """Capture stage and evidence and simulate canonical model output."""
        self.calls.append({'stage': self.stage, 'prompt': prompt, 'images': list(images)})
        if self.fail or len(self.calls) == self.fail_at:
            raise ValueError('Model request failed')
        piece = {'piece_type': 'Receipt or invoice', 'payer': '', 'payee': 'Supplier', 'other_names': [],
            'amount': '45.00', 'amount_location': 'page ' + str(self.pages), 'currency': 'RM', 'date': '',
            'document_number': 'INV-001', 'references': [], 'description': 'Supplies'}
        result = {'readable': True, 'description': 'Invoice', 'totals': [
            {'label': 'Invoice total', 'amount': '45.00', 'currency': 'RM', 'location': 'last page'}],
            'pieces': [piece]}
        if schema == pieces.ASSEMBLY:
            payload = next(json.loads(line) for line in reversed(prompt.splitlines())
                           if line.startswith('[{"source_unit":'))
            numbers = [unit['source_unit'] for unit in payload]
            if self.renumber:
                numbers = list(range(1, len(numbers) + 1))
            result['reviewed_units'] = numbers
            piece.update(source_units=numbers)
            if self.invalid:
                result['reviewed_units'].pop()
        validate(result, schema)
        return result


class PdfGroupsFixture(unittest.TestCase):
    """Reusable setUp and helpers; subclass it, or instantiate and call setUp() inside another test."""

    def prepare_pdf(self, pages, limit=5):
        """Prepare an isolated PDF and explicit config without customer inputs."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        root = base / 'documents'
        root.mkdir()
        with pymupdf.open() as pdf:
            for page in range(1, pages + 1):
                pdf.new_page().insert_text((40, 40), f'INV-001 page {page} of {pages} Supplies total MYR 45.00')
            pdf.save(root / 'invoice.pdf')
        config = base / 'config.json'
        config.write_text(json.dumps({**DEFAULTS, 'model': '', 'pdf_whole_document_max_pages': limit}))
        manifest, work = base / 'manifest.json', base / 'review'
        organize(root, manifest)
        workflow.prepare(manifest, work, config)
        index, state = workflow.load(work)
        return work, index, state

