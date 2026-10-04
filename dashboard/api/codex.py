"""Codex login status, version check and device-code login; usable before a workspace is selected."""

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from dashboard.services import codex_account

router = APIRouter(prefix="/api/codex")


@router.get("/status")
async def status(refresh: bool = False):
    """Report login method and versions; refresh=true also re-checks the latest release."""
    return await run_in_threadpool(codex_account.status, refresh)


@router.get("/login")
def login_state():
    """Report the device-code login in progress, without running Codex."""
    return codex_account.login_state()


@router.post("/login")
def login():
    """Start ChatGPT device-code login; the page shows the link and code to enter."""
    return codex_account.start_login()


@router.post("/login/cancel")
def cancel():
    """Stop a waiting device-code login."""
    return codex_account.cancel_login()
