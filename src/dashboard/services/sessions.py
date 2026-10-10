"""Isolate browser workspaces and lease each project to one active editor."""

import asyncio
import secrets
import threading
import time
from pathlib import Path

from fastapi import HTTPException

from dashboard.services.live_state import LiveState
from reconciliation.intake.workspace import SourceSelection

COOKIE = 'accounting_session'
LEASE_SECONDS = 300


class Context:
    """Own one browser session's selection, review, write lock and live snapshots."""

    def __init__(self, review, token, sources):
        """Create session state without modifying evidence or decisions."""
        self.review, self.token, self.sources = review, token, sources
        self.lock = asyncio.Lock()
        self.review_id = secrets.token_hex(16)
        self.session_id = None
        self.last_seen = time.monotonic()
        self.live = LiveState(self)


def jobs_running(review):
    """Keep ownership until background workers and their child processes have stopped."""
    return any(
        worker and worker.is_alive()
        for worker in (getattr(review, name, None) for name in ('content_thread', 'piece_match_thread'))
    ) or any(getattr(getattr(review, name, None), 'active_count', 0)
             for name in ('content_engine', 'piece_match_engine'))


class Sessions:
    """Manage process-local sessions and exclusive canonical-source leases."""

    def __init__(self, initial):
        """Keep explicit embedded startup state while isolating ordinary browser selections."""
        self.initial = initial
        self.entries = {}
        self.owners = {}
        self.lock = threading.RLock()

    def expire(self):
        """Release abandoned projects after five minutes, retaining running jobs."""
        now = time.monotonic()
        for state in self.entries.values():
            if state.review and now - state.last_seen >= LEASE_SECONDS and not state.lock.locked() and not jobs_running(state.review):
                self.release(state, state.review.root)
                state.review = None
                state.review_id = secrets.token_hex(16)

    def get(self, identity=None):
        """Accept only issued opaque cookies; renew the current browser's lease."""
        with self.lock:
            self.expire()
            state = self.entries.get(identity)
            if state is None:
                identity = secrets.token_urlsafe(32)
                if not self.entries and self.initial.review is not None:
                    state = self.initial
                else:
                    sources = SourceSelection(self.initial.sources.workspace,
                                              self.initial.sources.data / 'sessions' / identity)
                    state = Context(None, secrets.token_urlsafe(32), sources)
                state.session_id = identity
                self.entries[identity] = state
                if state.review:
                    self.claim(state, state.review.root)
            state.last_seen = time.monotonic()
            return state

    def fixture(self):
        """Bind injected fixture state to one simulated browser for stateless test clients."""
        with self.lock:
            state = self.initial
            state.session_id = secrets.token_urlsafe(32)
            self.entries[state.session_id] = state
            if state.review:
                self.claim(state, state.review.root)
            return state

    def touch(self, state):
        """Renew an issued session while its event stream remains connected."""
        with self.lock:
            if self.entries.get(state.session_id) is state:
                state.last_seen = time.monotonic()

    def claim(self, state, source):
        """Reserve the canonical supporting folder before any project setup writes."""
        with self.lock:
            self.expire()
            key = str(Path(source).resolve())
            owner = self.owners.get(key)
            if owner and owner != state.session_id:
                raise HTTPException(409, 'Project in use by another user. Try again after they close it.')
            self.owners[key] = state.session_id
            return key

    def release(self, state, source):
        """Release only this session's lease; never cancel another editor's work."""
        with self.lock:
            key = str(Path(source).resolve())
            if self.owners.get(key) == state.session_id:
                del self.owners[key]

    def in_use(self, state, source):
        """Report project availability without revealing another browser's identity."""
        with self.lock:
            self.expire()
            owner = self.owners.get(str(Path(source).resolve()))
            return owner is not None and owner != state.session_id

    async def close(self):
        """Finish every session's live readers during server shutdown."""
        hubs = {self.initial.live, *(state.live for state in self.entries.values())}
        await asyncio.gather(*(hub.close() for hub in hubs))
