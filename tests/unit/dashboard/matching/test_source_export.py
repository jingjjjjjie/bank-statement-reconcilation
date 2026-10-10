"""Verify original and matched archives preserve bytes and folder locations."""

import csv
from zipfile import ZipFile

from dashboard.services import source_export
from dashboard.services.matching import final_review
from reconciliation.intake.duplicates import fingerprint
from tests.fixtures.final_review import FinalReviewFixture


class SourceExportTests(FinalReviewFixture):
    def setUp(self):
        """Bind original source hashes and add non-document workspace inputs."""
        super().setUp()
        root = self.review.root
        (root / 'nested/empty').mkdir(parents=True)
        (root / 'nested/copy.txt').write_bytes((root / 'receipt-1.txt').read_bytes())
        self.manifest = {
            'SupportingRoot': str(root),
            'Files': [],
            'Mode': 'exact_report',
            'SourceHashes': {str(path): fingerprint(path) for path in root.rglob('*') if path.is_file()},
        }
        self.write(self.review.manifest_path, self.manifest)
        (root.parent / 'statement').mkdir()
        (root.parent / 'statement/bank.pdf').write_bytes(b'Original statement')
        (root.parent / 'notes.txt').write_bytes(b'Original notes')
        (root.parent / 'output').mkdir()
        (root.parent / 'output/generated.txt').write_bytes(b'Generated output')

    def archive(self, kind):
        """Read verified ZIP contents and clean up the temporary download."""
        path = source_export.export_zip(self.review, kind)
        try:
            with ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                return {name: archive.read(name) for name in archive.namelist()}
        finally:
            path.unlink()

    def test_originals_preserve_copies_and_empty_folders(self):
        """Original export retains every exact copy and empty folder without edits."""
        before = {path: path.read_bytes() for path in self.review.root.rglob('*') if path.is_file()}
        result = self.archive('original')
        for path, content in before.items():
            self.assertEqual(result['documents/' + path.relative_to(self.review.root).as_posix()], content)
            self.assertEqual(path.read_bytes(), content)
        self.assertIn('documents/nested/empty/', result)

    def test_project_contains_original_inputs_only(self):
        """Keep statement and other original inputs but exclude generated output."""
        result = self.archive('project')
        self.assertEqual(result['uploads/statement/bank.pdf'], b'Original statement')
        self.assertEqual(result['uploads/notes.txt'], b'Original notes')
        self.assertIn('uploads/documents/nested/copy.txt', result)
        self.assertFalse(any('/output/' in name for name in result))

    def test_only_current_confirmed_matches_are_exported(self):
        """Partial approved links include full originals and copies; undo removes them."""
        self.assertEqual(self.archive('matched'), {'documents/': b''})
        final_review.decide(self.review, self.request(allocations=[{'item_id': 'D1', 'amount': '4'}]))
        ledger = (self.project / 'final-review/decisions.json').read_bytes()
        result = self.archive('matched')
        self.assertEqual(set(result), {'documents/', 'documents/receipt-1.txt', 'documents/nested/copy.txt'})
        self.assertEqual((self.project / 'final-review/decisions.json').read_bytes(), ledger)
        final_review.decide(self.review, self.request(action='undo'))
        self.assertEqual(self.archive('matched'), {'documents/': b''})

    def test_changed_or_missing_original_is_not_called_initial_state(self):
        """Fail clearly if original intake bytes can no longer be recovered."""
        source = self.review.root / 'receipt-1.txt'
        source.write_bytes(b'Changed bytes')
        with self.assertRaisesRegex(ValueError, 'changed since intake'):
            self.archive('original')
        source.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.archive('project')

    def bind_statement(self, kind):
        """Record fixture statement provenance using the implemented master or import format."""
        statement = self.review.root.parent / 'statement/bank.pdf'
        row = {'source': str(statement), 'source_sha256': fingerprint(statement).lower()}
        if kind == 'master':
            with (self.project / 'bank-output/master_statement.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
        else:
            directory = self.project / 'final-review'
            directory.mkdir(exist_ok=True)
            self.write(
                directory / 'bank-import.json',
                {
                    'manifest': str(self.review.manifest_path.resolve()),
                    'banks': [row],
                },
            )
        return statement

    def test_master_statement_hash_rejects_changed_and_missing_original(self):
        """An original project archive must retain the statement used by its bank master."""
        statement = self.bind_statement('master')
        self.assertEqual(self.archive('project')['uploads/statement/bank.pdf'], b'Original statement')
        statement.write_bytes(b'Changed statement')
        with self.assertRaisesRegex(ValueError, 'statement changed since extraction'):
            self.archive('project')
        statement.unlink()
        with self.assertRaisesRegex(ValueError, 'statement is missing'):
            self.archive('project')

    def test_imported_statement_hash_rejects_changed_and_missing_original(self):
        """A manifest-bound imported bank snapshot protects its statement's original bytes."""
        statement = self.bind_statement('import')
        self.assertEqual(self.archive('project')['uploads/statement/bank.pdf'], b'Original statement')
        statement.write_bytes(b'Changed statement')
        with self.assertRaisesRegex(ValueError, 'statement changed since extraction'):
            self.archive('project')
        statement.unlink()
        with self.assertRaisesRegex(ValueError, 'statement is missing'):
            self.archive('project')

    def test_unbound_import_cannot_supply_another_workspaces_provenance(self):
        """Reject a bank import whose saved manifest points at a different project."""
        self.bind_statement('import')
        path = self.project / 'final-review/bank-import.json'
        saved = final_review.read(path)
        saved['manifest'] = str(self.project / 'other-manifest.json')
        self.write(path, saved)
        with self.assertRaisesRegex(ValueError, 'another workspace'):
            self.archive('project')

    def test_legacy_statement_without_saved_hash_retains_export_compatibility(self):
        """Do not invent historical hashes for older statement rows or extra input files."""
        statement = self.review.root.parent / 'statement/bank.pdf'
        statement.write_bytes(b'Current legacy statement')
        (statement.parent.parent / 'notes.txt').write_bytes(b'Current notes')
        result = self.archive('project')
        self.assertEqual(result['uploads/statement/bank.pdf'], b'Current legacy statement')
        self.assertEqual(result['uploads/notes.txt'], b'Current notes')
