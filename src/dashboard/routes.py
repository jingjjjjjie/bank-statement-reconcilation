"""FastAPI application, local request protection, and Vue asset delivery."""

import asyncio
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from jsonschema.exceptions import ValidationError as SchemaValidationError

from reconciliation.intake.workspace import SourceSelection

FRONTEND = Path(os.environ.get("DASHBOARD_FRONTEND", Path(__file__).parent / "frontend/dist"))
# Evidence edits submit complete piece lists; small control requests keep their tighter bound.
EVIDENCE_REQUEST_PATHS = {
    "/api/receipts/accept",
    "/api/receipts/accept-all",
    "/api/receipts/merge-all",
    "/api/matching-decide",
}
MAX_EVIDENCE_REQUEST_BYTES = 1024 * 1024
MAX_CONTROL_REQUEST_BYTES = 8192
PAGES = {
    "",
    "home",
    "accounting-finance",
    "projects",
    "source",
    "review",
    "exact-report",
    "content-review",
    "documents",
    "bank",
    "matching",
    "final-report",
    "extraction-review",
    "settings",
    "complete",
}


class Context:
    """Keep the active review and serialized file decisions in one server process."""

    def __init__(self, review, token, sources):
        """Create one session without changing saved workflow state."""
        self.review, self.token, self.sources = review, token, sources
        self.lock = asyncio.Lock()
        self.review_id = secrets.token_hex(16)


async def context(request: Request):
    """Wait for workflow access without occupying request-worker threads."""
    state = request.app.state.context
    async with state.lock:
        expected = request.headers.get("X-Review-Id")
        if request.method == "POST" and expected and expected != state.review_id:
            raise HTTPException(409, "The active workspace changed. Reload this page before saving.")
        yield state


async def interrupt_context(request: Request):
    """Allow cancellation and status reads to bypass slow workflow requests."""
    state = request.app.state.context
    expected = request.headers.get("X-Review-Id")
    if request.method == "POST" and expected and expected != state.review_id:
        raise HTTPException(409, "The active workspace changed. Reload this page before saving.")
    if state.review is None:
        raise HTTPException(409, "Select a workspace and proceed first")
    return state.review


def active_context(state=Depends(context)):
    """Require an active project while holding its decision lock."""
    if state.review is None:
        raise HTTPException(409, "Select a workspace and proceed first")
    return state


def create_app(review=None, token=None, sources=None):
    """Build the ASGI app without starting a server or performing model calls."""
    from dashboard.api import codex, files, live, review as review_api, source
    from dashboard.services.live_state import LiveState

    workspace = Path(__file__).resolve().parents[2]
    sources = sources or (
        SourceSelection(review.manifest_path.parent, review.data)
        if review
        else SourceSelection(workspace, workspace / "src/dashboard/.data")
    )

    @asynccontextmanager
    async def lifespan(app):
        """Finish display workers before the application releases its workspace."""
        try:
            yield
        finally:
            await app.state.live.close()

    app = FastAPI(lifespan=lifespan, title="Reconciliation dashboard", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.context = Context(review, token or secrets.token_urlsafe(32), sources)
    app.state.live = LiveState(app.state.context)
    app.include_router(live.router)
    allowed_hosts = {
        host.strip().lower() for host in os.environ.get('DASHBOARD_ALLOWED_HOSTS', '').split(',') if host.strip()
    }

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        """Allow explicitly configured LAN addresses while retaining browser write protection."""
        port = request.scope["server"][1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"} | allowed_hosts
        host = request.headers.get('host', '').lower()
        if host not in hosts:
            return JSONResponse({"error": "Dashboard address is not allowed"}, status_code=403)
        if request.method == "POST":
            origin = request.headers.get("origin")
            if request.headers.get("X-Review-Token") != app.state.context.token or (
                origin and origin != f"http://{host}"
            ):
                return JSONResponse({"error": "Refresh the dashboard before making changes"}, status_code=403)
            body = bytearray()
            limit = (
                MAX_EVIDENCE_REQUEST_BYTES if request.url.path in EVIDENCE_REQUEST_PATHS else MAX_CONTROL_REQUEST_BYTES
            )
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > limit:
                    return JSONResponse({"error": "Invalid request size"}, status_code=413)
            if not body:
                return JSONResponse({"error": "Invalid request size"}, status_code=400)
            request._body = bytes(body)
        response = await call_next(request)
        if request.method == "POST" and response.status_code < 400:
            app.state.live.invalidate()
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        """Keep the JSON error shape consumed by every dashboard view."""
        return JSONResponse({"error": str(error.detail)}, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        """Report invalid fields without returning private input contents."""
        return JSONResponse({"error": "Invalid request fields"}, status_code=422)

    @app.exception_handler(SchemaValidationError)
    async def invalid_evidence(request, error):
        """Return a readable validation error rather than an unparseable server failure."""
        location = ".".join(str(part) for part in error.absolute_path) or "submitted evidence"
        return JSONResponse({"error": f"Invalid {location}: {error.message}"}, status_code=422)

    @app.exception_handler(ValueError)
    @app.exception_handler(OSError)
    @app.exception_handler(KeyError)
    @app.exception_handler(IndexError)
    async def workflow_error(request, error):
        """Translate expected workflow failures to readable API errors."""
        status = 404 if isinstance(error, (FileNotFoundError, KeyError, IndexError)) else 400
        return JSONResponse({"error": str(error)}, status_code=status)

    @app.get("/api/session")
    async def session():
        """Return routing metadata without scanning documents or acquiring a workflow lock."""
        state = app.state.context
        return {
            "token": state.token,
            "review_id": state.review_id,
            "active": state.review is not None,
            "mode": state.review.manifest.get("Mode", "legacy") if state.review else None,
        }

    app.include_router(source.router)
    app.include_router(review_api.router)
    app.include_router(files.router)
    app.include_router(codex.router)

    @app.get("/assets/{name:path}")
    def asset(name: str):
        """Serve bundled frontend files with immutable content-hashed URLs."""
        root = (FRONTEND / "assets").resolve()
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, "Asset not found")
        return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/{page:path}")
    def page(page: str, request: Request):
        """Support direct links and browser history for known Vue routes."""
        if page.strip("/") not in PAGES:
            raise HTTPException(404, "File or page not found")
        index = FRONTEND / "index.html"
        if not index.is_file():
            raise HTTPException(503, "Build the frontend first: cd src/dashboard/frontend && npm ci && npm run build")
        body = index.read_bytes()
        etag = chr(34) + hashlib.sha256(body).hexdigest() + chr(34)
        headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
        cached = request.headers.get("if-none-match") == etag
        return Response(
            b"" if cached else body, status_code=304 if cached else 200, media_type="text/html", headers=headers
        )

    return app
