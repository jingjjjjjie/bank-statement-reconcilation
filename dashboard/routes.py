"""FastAPI application, local request protection, and Vue asset delivery."""
import asyncio
import hashlib
import os
import secrets
from pathlib import Path
from jsonschema.exceptions import ValidationError as SchemaValidationError

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response

from reconciliation.source_selection import SourceSelection

FRONTEND = Path(os.environ.get("DASHBOARD_FRONTEND", Path(__file__).parent / "frontend/dist"))
PAGES = {"", "source", "review", "exact-report", "content-review", "documents", "bank",
         "matching", "final-report", "extraction-review", "settings", "complete"}


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
    from dashboard.api import files, review as review_api, source

    workspace = Path(__file__).resolve().parent.parent
    sources = sources or (SourceSelection(review.manifest_path.parent, review.data) if review else
                          SourceSelection(workspace, workspace / "dashboard/.data"))
    app = FastAPI(title="Reconciliation dashboard", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.context = Context(review, token or secrets.token_urlsafe(32), sources)

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        """Retain loopback, origin, token, size, and browser security checks."""
        port = request.scope["server"][1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if request.headers.get("host") not in hosts:
            return JSONResponse({"error": "Local access only"}, status_code=403)
        if request.method == "POST":
            origin = request.headers.get("origin")
            if (request.headers.get("X-Review-Token") != app.state.context.token or
                    (origin and origin not in {f"http://{host}" for host in hosts})):
                return JSONResponse({"error": "Refresh the dashboard before making changes"}, status_code=403)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 8192:
                    return JSONResponse({"error": "Invalid request size"}, status_code=413)
            if not body:
                return JSONResponse({"error": "Invalid request size"}, status_code=400)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'"
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
        return {"token": state.token, "review_id": state.review_id,
                "active": state.review is not None,
                "mode": state.review.manifest.get("Mode", "legacy") if state.review else None}

    app.include_router(source.router)
    app.include_router(review_api.router)
    app.include_router(files.router)

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
            raise HTTPException(503, "Build the frontend first: cd dashboard/frontend && npm ci && npm run build")
        body = index.read_bytes()
        etag = chr(34) + hashlib.sha256(body).hexdigest() + chr(34)
        headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
        cached = request.headers.get("if-none-match") == etag
        return Response(b"" if cached else body, status_code=304 if cached else 200,
                        media_type="text/html", headers=headers)

    return app
