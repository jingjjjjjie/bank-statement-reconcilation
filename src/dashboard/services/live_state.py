"""Shared display snapshots and live notifications; never used to authorize writes or exports."""

import asyncio
import json
import time
from pathlib import Path

from fastapi.responses import Response


def signature(review):
    """Detect changed display inputs cheaply; periodic full reads still verify original bytes."""
    if review is None:
        return ()
    project = review.manifest_path.parent
    paths = {review.manifest_path}
    for folder in ('review', 'final-review', 'bank-output', 'dashboard-data'):
        for pattern in ('*.json', '*.csv'):
            paths.update((project / folder).glob(pattern))
    if not (project / 'final-review/piece-pipeline.json').exists():
        from dashboard.services.matching.final_review import CACHE

        paths.update(CACHE.rglob('*.json'))
    index = project / 'review/index.json'
    if index.exists():
        for document in json.loads(index.read_text(encoding='utf-8'))['documents'].values():
            paths.update(Path(path) for path in document['paths'])
            paths.update(Path(unit['image']) for unit in document['units'] if unit.get('image'))
    for folder in (review.root, review.root.parent / 'statement'):
        if folder.exists():
            paths.update(path for path in folder.rglob('*') if path.is_file())
    result = []
    for path in sorted(paths):
        try:
            stat = path.stat()
            result.append((str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino))
        except OSError:
            result.append((str(path), None))
    return tuple(result)


class LiveState:
    """Coalesce display reads per workspace and notify browsers when verified snapshots change."""

    def __init__(self, context):
        """Create an empty, process-local display cache with no persistent decision state."""
        self.context = context
        self.review_id = context.review_id
        self.epoch = 0
        self.slots = {}
        self.tasks = set()
        self.listeners = set()
        self.monitor = None
        self.closed = False
        self.last_signature = None
        self.progress = {}

    def start(self):
        """Run one observer for all browser tabs, created only when the app is used."""
        if self.monitor is None:
            self.monitor = asyncio.create_task(self.watch())

    def workspace(self):
        """Prevent a previous workspace's cached data from reaching the active one."""
        if self.review_id != self.context.review_id:
            self.review_id = self.context.review_id
            self.epoch += 1
            self.slots = {}
            self.last_signature = None
            self.progress = {}
            self.publish({'kind': 'workspace'})

    def publish(self, event):
        """Send bounded notifications; a reconnect receives every current snapshot revision."""
        event = {**event, 'review_id': self.review_id}
        for queue in tuple(self.listeners):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def invalidate(self):
        """Schedule fresh display reads after a successful mutation; retain the last display meanwhile."""
        self.workspace()
        self.epoch += 1
        self.publish({'kind': 'updating'})
        for path, slot in self.slots.items():
            self.schedule(path, slot)

    def schedule(self, path, slot):
        """Allow only one expensive read per snapshot kind at a time."""
        if not self.closed and (slot.get('task') is None or slot['task'].done()):
            slot['task'] = asyncio.create_task(self.build(path, slot))
            self.tasks.add(slot['task'])
            slot['task'].add_done_callback(self.tasks.discard)

    async def build(self, path, slot):
        """Verify current evidence off the event loop, then atomically replace the display."""
        epoch, review_id, review = self.epoch, self.review_id, self.context.review
        try:
            data = await asyncio.to_thread(slot['loader'], review)
            body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()
            if review_id != self.context.review_id:
                return
            changed = body != slot.get('body') or epoch != slot['epoch']
            slot.update(body=body, epoch=epoch, error=None, checked=time.monotonic())
            if changed:
                slot['version'] += 1
            if path == '/api/workflow-checks' and any(
                step['href'] == '/matching' and step.get('available') for step in data['steps']
            ):
                from dashboard.services.matching.final_review import snapshot

                warm = self.slots.setdefault('/api/matching', {'loader': snapshot, 'version': 0, 'epoch': -1})
                if warm['epoch'] != self.epoch:
                    self.schedule('/api/matching', warm)
            if changed:
                self.publish(
                    {'kind': 'snapshot', 'path': path, 'version': slot['version'], 'updating': epoch != self.epoch}
                )
        except (OSError, ValueError, KeyError) as error:
            slot.update(error=str(error), epoch=epoch, checked=time.monotonic())
            if review_id == self.context.review_id:
                self.publish({'kind': 'error', 'path': path, 'error': str(error)})

    async def response(self, path, loader, *, allow_stale=False):
        """Serve a prepared display immediately; cold requests share a single verified load."""
        self.workspace()
        self.start()
        if not allow_stale:
            current = await asyncio.to_thread(signature, self.context.review)
            if self.last_signature is not None and current != self.last_signature:
                self.invalidate()
            self.last_signature = current
        review_id = self.review_id
        slot = self.slots.setdefault(path, {'loader': loader, 'version': 0, 'epoch': -1})
        if slot['epoch'] != self.epoch:
            self.schedule(path, slot)
        while ('body' not in slot or (not allow_stale and slot['epoch'] != self.epoch)) and not slot.get('error'):
            self.schedule(path, slot)
            await asyncio.shield(slot['task'])
            if review_id != self.context.review_id:
                break
        if review_id != self.context.review_id:
            raise ValueError('The active workspace changed. Reload this page.')
        if slot.get('error'):
            raise ValueError(slot['error'])
        return Response(
            slot['body'],
            media_type='application/json',
            headers={
                'X-Workspace-Revision': str(slot['version']),
                'X-Workspace-Updating': str(slot['epoch'] != self.epoch).lower(),
            },
        )

    async def watch(self):
        """Watch saved inputs and share lightweight job progress across connected browsers."""
        from dashboard.services.extraction.extraction_runs import execution_status
        from dashboard.services.matching.piece_match_jobs import status

        scanned, syncing, progress_epoch = 0.0, None, -1
        while not self.closed:
            self.workspace()
            review = self.context.review
            review_id = self.review_id
            try:
                if time.monotonic() - scanned >= 2:
                    current = await asyncio.to_thread(signature, review)
                    if review_id != self.context.review_id:
                        continue
                    if self.last_signature is not None and current != self.last_signature:
                        self.invalidate()
                    self.last_signature, scanned = current, time.monotonic()
                for path, slot in tuple(self.slots.items()):
                    if slot['epoch'] != self.epoch or time.monotonic() - slot.get('checked', 0) >= 60:
                        self.schedule(path, slot)
                if review is not None and self.listeners:
                    for path, loader in (('/api/content/execution', execution_status), ('/api/matching-run', status)):
                        previous = self.progress.get(path, {})
                        worker = getattr(review, 'piece_match_thread', None)
                        if (
                            path == '/api/matching-run'
                            and progress_epoch == self.epoch
                            and previous
                            and not previous.get('running')
                            and not (worker and worker.is_alive())
                        ):
                            continue
                        data = await asyncio.to_thread(loader, review)
                        if review_id != self.context.review_id:
                            break
                        if data != self.progress.get(path):
                            self.progress[path] = data
                            self.publish({'kind': 'progress', 'path': path, 'data': data})
                    progress_epoch = self.epoch
            except (OSError, ValueError, KeyError):
                # A checkpoint may be between writes; the next scan retries without claiming fresh state.
                pass
            busy = any(
                slot['epoch'] != self.epoch or (slot.get('task') and not slot['task'].done())
                for slot in self.slots.values()
            )
            if busy != syncing:
                syncing = busy
                self.publish({'kind': 'sync', 'updating': busy})
            await asyncio.sleep(0.5)

    async def close(self):
        """Stop observation and finish in-flight reads before releasing workspace files."""
        self.closed = True
        if self.monitor:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
