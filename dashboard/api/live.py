"""One same-origin event stream for workspace display and job progress."""

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix='/api')


@router.get('/live')
async def live(request: Request):
    """Replay current revisions on reconnect, then send only changed state."""
    hub = request.app.state.live
    hub.workspace()
    hub.start()
    queue = asyncio.Queue(maxsize=64)
    hub.listeners.add(queue)
    for path, slot in hub.slots.items():
        if 'body' in slot:
            queue.put_nowait({'kind': 'snapshot', 'path': path, 'version': slot['version'], 'review_id': hub.review_id})

    for path, data in hub.progress.items():
        queue.put_nowait({'kind': 'progress', 'path': path, 'data': data, 'review_id': hub.review_id})
    queue.put_nowait(
        {
            'kind': 'sync',
            'updating': any(slot['epoch'] != hub.epoch for slot in hub.slots.values()),
            'review_id': hub.review_id,
        }
    )

    async def events():
        """Release the subscription when the tab closes or its network disconnects."""
        try:
            yield ': connected\n\n'
            while not hub.closed and not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5)
                    yield 'data: ' + json.dumps(event) + '\n\n'
                except asyncio.TimeoutError:
                    yield ': heartbeat\n\n'
        finally:
            hub.listeners.discard(queue)

    return StreamingResponse(events(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})
