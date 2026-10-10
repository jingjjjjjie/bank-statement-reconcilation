"""Protect shared Codex capacity with one extraction batch across projects."""

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from dashboard.services.extraction import extraction_runs, regeneration
from tests.fixtures.extraction_runs import ExtractionRunsFixture, FixtureReviewer


class ExtractionSlotTests(unittest.TestCase):
    """Use fake reviewers and bounded synthetic workers, never live Codex calls."""

    def setUp(self):
        """Prepare two separate projects and restore the process-wide slot after each test."""
        owner = patch.object(extraction_runs, '_batch_owner', None)
        owner.start()
        self.addCleanup(owner.stop)
        self.reviews = []
        for _ in range(2):
            fixture = ExtractionRunsFixture()
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            extraction_runs.prepare(fixture.review)
            self.reviews.append(fixture.review)

    def test_parallel_launches_have_one_winner_and_release_after_finish(self):
        """Only one project launches Codex; another can start after verified worker exit."""
        entered, release = threading.Event(), threading.Event()

        def hold(*args, **kwargs):
            """Hold a synthetic batch while the other project attempts admission."""
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError('Fixture worker not released')

        def launch(review):
            """Return the accepted run or its explicit capacity conflict."""
            try:
                extraction_runs.start(review)
                return True
            except ValueError as error:
                self.assertEqual(str(error), extraction_runs.BLOCKED_MESSAGE)
                return False

        with patch.object(extraction_runs, 'run', hold), patch.object(
            extraction_runs, 'CodexReviewer', side_effect=lambda *args, **kwargs: FixtureReviewer()
        ) as calls:
            try:
                with ThreadPoolExecutor(2) as pool:
                    accepted = list(pool.map(launch, self.reviews))
                self.assertEqual(sorted(accepted), [False, True])
                self.assertTrue(entered.wait(timeout=2))
                waiting = self.reviews[accepted.index(False)]
                self.assertTrue(extraction_runs.execution_status(waiting)['blocked'])
                self.assertFalse(extraction_runs.execution_status(waiting)['running'])
                self.assertEqual(calls.call_count, 1)
                # Regeneration cannot write queue state before gaining admission.
                self.assertFalse(regeneration.queue_path(waiting).exists())
                with self.assertRaisesRegex(ValueError, 'another project'):
                    regeneration.enqueue(waiting, 'fixture')
                self.assertFalse(regeneration.queue_path(waiting).exists())
            finally:
                release.set()
                for review in self.reviews:
                    worker = getattr(review, 'content_thread', None)
                    if worker:
                        worker.join(timeout=5)
            self.assertFalse(extraction_runs.execution_status(waiting)['blocked'])
            extraction_runs.start(waiting)
            waiting.content_thread.join(timeout=5)
            self.assertEqual(calls.call_count, 2)
            self.assertFalse(extraction_runs.execution_status(waiting)['running'])

    def test_unverified_child_process_keeps_slot_reserved(self):
        """A dead worker does not free shared capacity while a child is still active."""
        engine = SimpleNamespace(active_count=1)
        owner = SimpleNamespace(content_thread=None, content_engine=engine)
        extraction_runs._batch_owner = owner
        waiting = self.reviews[1]
        self.assertTrue(extraction_runs.execution_status(waiting)['blocked'])
        with self.assertRaisesRegex(ValueError, 'another project'):
            extraction_runs.start(waiting)
        engine.active_count = 0
        self.assertFalse(extraction_runs.execution_status(waiting)['blocked'])

    def test_failed_validation_does_not_reserve_slot(self):
        """An invalid launch leaves another project able to start immediately."""
        with patch.object(extraction_runs, 'active_config', side_effect=ValueError('invalid settings')):
            with self.assertRaisesRegex(ValueError, 'invalid settings'):
                extraction_runs.start(self.reviews[0])
        self.assertIsNone(extraction_runs._batch_owner)
        self.assertFalse(extraction_runs.execution_status(self.reviews[1])['blocked'])
