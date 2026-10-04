"""Verify display caching cannot mix workspaces or hide failed refreshes."""

import asyncio
import json
import threading
import unittest
from types import SimpleNamespace

from dashboard.services.live_state import LiveState


class LiveStateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        """Use isolated in-memory loaders without real evidence or background jobs."""
        self.context = SimpleNamespace(review_id='first', review=None)
        self.hub = LiveState(self.context)
        self.addAsyncCleanup(self.hub.close)

    async def test_reads_coalesce_and_refresh_without_blocking_cached_display(self):
        """Concurrent tabs share one load and retain old display during a verified refresh."""
        calls, version = [], [1]
        entered, release = threading.Event(), threading.Event()
        release.set()

        def load(review):
            """Hold a deterministic read to exercise in-flight refreshes."""
            calls.append(version[0])
            entered.set()
            release.wait(3)
            return {'version': version[0]}

        replies = await asyncio.gather(*[self.hub.response('/test', load, allow_stale=True) for _ in range(3)])
        self.assertEqual(calls, [1])
        self.assertTrue(all(json.loads(response.body)['version'] == 1 for response in replies))
        version[0] = 2
        release.clear()
        self.hub.invalidate()
        response = await self.hub.response('/test', load, allow_stale=True)
        self.assertEqual(json.loads(response.body), {'version': 1})
        self.assertEqual(response.headers['X-Workspace-Updating'], 'true')
        release.set()
        fresh = await self.hub.response('/test', load)
        self.assertEqual(json.loads(fresh.body), {'version': 2})
        self.assertEqual(fresh.headers['X-Workspace-Updating'], 'false')

    async def test_workspace_change_discards_old_display(self):
        """A new project never receives the old project's retained snapshot."""
        await self.hub.response('/test', lambda review: {'project': 1}, allow_stale=True)
        self.context.review_id = 'second'
        response = await self.hub.response('/test', lambda review: {'project': 2}, allow_stale=True)
        self.assertEqual(json.loads(response.body), {'project': 2})
        self.assertEqual(self.hub.review_id, 'second')

    async def test_failed_refresh_does_not_claim_cached_evidence_is_current(self):
        """Retained display cannot silently replace a failed current verification."""
        fail = [False]

        def load(review):
            """Simulate a source that becomes invalid after an initially successful read."""
            if fail[0]:
                raise ValueError('Source changed')
            return {'valid': True}

        await self.hub.response('/test', load, allow_stale=True)
        fail[0] = True
        self.hub.invalidate()
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            await self.hub.response('/test', load)

    async def test_inflight_old_workspace_cannot_publish_into_new_workspace(self):
        """Switching during an expensive read rejects its response and retains only the new project."""
        entered, release = threading.Event(), threading.Event()

        def slow(review):
            """Hold the old workspace read until the new workspace has loaded."""
            entered.set()
            release.wait(3)
            return {'project': 'old'}

        pending = asyncio.create_task(self.hub.response('/test', slow, allow_stale=True))
        await asyncio.to_thread(entered.wait, 2)
        self.context.review_id = 'second'
        fresh = await self.hub.response('/test', lambda review: {'project': 'new'}, allow_stale=True)
        release.set()
        with self.assertRaisesRegex(ValueError, 'workspace changed'):
            await pending
        self.assertEqual(json.loads(fresh.body), {'project': 'new'})
        self.assertEqual(json.loads(self.hub.slots['/test']['body']), {'project': 'new'})
