"""Ensure read-only media never waits for decision/status work or skips validation."""
import concurrent.futures
import json
import threading
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import patch

from dashboard import matching_review
from dashboard.routes import create_app
from tests.http_server import TestServer
from tests.unit import test_matching_review as fixtures


class MatchingMediaSpeedTests(unittest.TestCase):
    def setUp(self):
        """Serve isolated evidence and ledger fixtures without touching real decisions."""
        self.fixture = fixtures.MatchingReviewTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.app = create_app(self.fixture.review, 'token', SimpleNamespace())
        self.server = TestServer(('127.0.0.1', 0), self.app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def get(self, path):
        """Read one request with a bounded timeout to expose lock contention."""
        with urllib.request.urlopen(self.base + path, timeout=3) as response:
            return response.read()

    def test_media_bypasses_busy_workflow_lock(self):
        """A blocked status check must not delay validated evidence metadata or pages."""
        started, release = threading.Event(), threading.Event()

        def slow_workflow(review):
            """Hold the workflow lock until the media requests have completed."""
            started.set()
            release.wait(8)
            return {'steps': []}

        with patch('dashboard.api.review.workflow_guide', slow_workflow), concurrent.futures.ThreadPoolExecutor() as pool:
            check = pool.submit(self.get, '/api/workflow-checks')
            try:
                self.assertTrue(started.wait(2))
                snapshot = json.loads(self.get('/api/matching'))
                self.assertEqual(len(snapshot['banks']), 3)
                response = json.loads(self.get('/api/matching-preview?kind=item&id=D1'))
                self.assertEqual(response['kind'], 'text')
                with patch('dashboard.api.files.extraction_preview.image', return_value=b'preview'):
                    self.assertEqual(self.get('/api/matching-image?kind=item&id=D1&page=0'), b'preview')
                with patch('dashboard.api.files.office_preview.page', return_value={'kind': 'spreadsheet'}):
                    self.assertEqual(json.loads(self.get('/api/matching-office?kind=item&id=D1&page=0'))['kind'], 'spreadsheet')
            finally:
                release.set()
            check.result()

    def test_changed_sources_and_unknown_ids_still_fail(self):
        """Removing lock contention must retain original-byte and corpus membership checks."""
        self.get('/api/matching-preview?kind=item&id=D1')
        (self.fixture.review.root / 'receipt-1.txt').write_text('Changed source')
        for path, code in [('/api/matching-preview?kind=item&id=D1', 400),
                           ('/api/matching-image?kind=item&id=D1&page=0', 400),
                           ('/api/matching-office?kind=item&id=D1&page=0', 400),
                           ('/api/matching-preview?kind=item&id=unknown', 404)]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.get(path)
            self.assertEqual(error.exception.code, code)

    def test_bank_statement_hashed_once_per_snapshot(self):
        """Repeated transaction references do not rehash the same statement."""
        with patch.object(matching_review, 'source_hash', wraps=matching_review.source_hash) as hashes:
            matching_review.snapshot(self.fixture.review)
        statement = str(self.fixture.root / 'statement.txt')
        self.assertEqual(sum(call.args[0] == statement for call in hashes.call_args_list), 1)

    def test_step2_native_image_is_fast_and_still_validated(self):
        """Step 2 sends original JPEG bytes despite a busy workflow, rejecting later edits."""
        from PIL import Image
        from reconciliation.duplicate_workflow import fingerprint
        source = self.fixture.root / 'large-original.jpg'
        Image.new('RGB', (1600, 1200), 'white').save(source)
        digest = fingerprint(source)
        original = source.read_bytes()
        index = {'documents': {digest: {'paths': [str(source)]}}}
        started, release = threading.Event(), threading.Event()

        def slow_workflow(review):
            """Keep an unrelated workflow check busy during preview requests."""
            started.set()
            release.wait(8)
            return {'steps': []}

        with patch('dashboard.content_review.load_index', return_value=(index, 'fixture')), \
             patch('dashboard.api.review.workflow_guide', slow_workflow), \
             concurrent.futures.ThreadPoolExecutor() as pool:
            check = pool.submit(self.get, '/api/workflow-checks')
            try:
                self.assertTrue(started.wait(2))
                info = json.loads(self.get('/api/extraction-preview?id=' + digest))
                self.assertEqual(info['kind'], 'image')
                with patch('dashboard.api.files.extraction_preview.image', side_effect=AssertionError('unnecessary PNG conversion')):
                    with urllib.request.urlopen(self.base + '/api/extraction-preview-image?id=' + digest, timeout=3) as response:
                        self.assertEqual(response.headers.get_content_type(), 'image/jpeg')
                        self.assertEqual(response.read(), original)
                with patch('dashboard.api.files.office_preview.page', return_value={'kind': 'spreadsheet'}):
                    self.assertEqual(json.loads(self.get('/api/extraction-office?id=' + digest))['kind'], 'spreadsheet')
                source.write_bytes(original + b'changed')
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.get('/api/extraction-preview-image?id=' + digest)
                self.assertEqual(error.exception.code, 400)
            finally:
                release.set()
            check.result()

    def test_header_check_does_not_block_save(self):
        """A slow header check must not hold the decision lock needed by Accept & next."""
        started, release = threading.Event(), threading.Event()

        def slow_workflow(review):
            """Hold header computation until the save endpoint has responded."""
            started.set()
            release.wait(8)
            return {'steps': []}

        with patch('dashboard.api.review.workflow_guide', slow_workflow), \
             patch('dashboard.receipt_review.accept_extraction', return_value={'saved': True}), \
             concurrent.futures.ThreadPoolExecutor() as pool:
            check = pool.submit(self.get, '/api/workflow-checks')
            try:
                self.assertTrue(started.wait(2))
                request = urllib.request.Request(self.base + '/api/receipts/accept', b'{}',
                    {'Content-Type': 'application/json', 'X-Review-Token': 'token'})
                with urllib.request.urlopen(request, timeout=3) as response:
                    self.assertTrue(json.load(response)['saved'])
            finally:
                release.set()
            check.result()
