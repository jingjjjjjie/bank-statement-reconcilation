"""Codex login status, version check and device-code login; usable before a workspace is selected."""

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from dashboard.services import codex_account

router = APIRouter(prefix="/api/codex")


def local(request: Request):
    """Whether the request comes through the dashboard's own computer address, not a LAN address."""
    return request.headers.get("host", "").lower().rsplit(":", 1)[0] in {"127.0.0.1", "localhost"}


def this_computer(request: Request):
    """Allow login changes only on the dashboard's own computer."""
    if not local(request):
        raise HTTPException(403, "Codex login can only be changed on the dashboard computer")


def visible(login, request):
    """Hide the sign-in link, code and output from other computers so they cannot finish the login."""
    return login if local(request) else {**login, "url": "", "code": "", "lines": []}


@router.get("/status")
async def status(request: Request, refresh: bool = False):
    """Report login method and versions; refresh=true also re-checks the latest release."""
    data = await run_in_threadpool(codex_account.status, refresh)
    return {**data, "login": visible(data["login"], request)}


@router.get("/login")
def login_state(request: Request):
    """Report the device-code login in progress, without running Codex."""
    return visible(codex_account.login_state(), request)


@router.post("/login", dependencies=[Depends(this_computer)])
def login():
    """Start ChatGPT device-code login; the page shows the link and code to enter."""
    return codex_account.start_login()


@router.post("/login/cancel", dependencies=[Depends(this_computer)])
def cancel():
    """Stop a waiting device-code login."""
    return codex_account.cancel_login()
