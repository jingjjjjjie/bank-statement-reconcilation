"""Confirmed workspace lifecycle actions with session ownership and worker guards."""

import asyncio
import secrets

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from dashboard.routes import context
from dashboard.services import project_actions
from dashboard.services.live_state import LiveState
from dashboard.services.sessions import jobs_running

router = APIRouter(prefix='/api/projects')


class ProjectAction(BaseModel):
    """Use a server-discovered identity instead of trusting a browser filesystem path."""

    id: str = Field(pattern=r'^[0-9a-f]{24}$')


async def perform(body, request, state, action):
    """Exclude other editors and running jobs before archiving project outputs."""
    manifest, source, saved = project_actions.locate(state.sources, body.id)
    active = state.review is not None and state.review.manifest_path == manifest
    if active and jobs_running(state.review):
        raise ValueError('Stop document processing and matching before resetting or deleting this workspace')
    sessions = request.app.state.sessions
    sessions.claim(state, source)
    if active:
        await state.live.close()
    try:
        review = await asyncio.to_thread(project_actions.change, state.sources, manifest, source, saved, action)
        if active:
            state.review = review
            state.review_id = secrets.token_hex(16)
            if action == 'delete':
                state.sources.active.unlink(missing_ok=True)
        return {'action': action, 'id': body.id}
    finally:
        if active:
            state.live = LiveState(state)
        if not active or state.review is None:
            sessions.release(state, source)


@router.post('/reset')
async def reset(body: ProjectAction, request: Request, state=Depends(context)):
    """Return a saved workspace to freshly prepared inputs without model calls."""
    return await perform(body, request, state, 'reset')


@router.post('/delete')
async def delete(body: ProjectAction, request: Request, state=Depends(context)):
    """Remove a workspace from the app, retaining original files and archived history."""
    return await perform(body, request, state, 'delete')
