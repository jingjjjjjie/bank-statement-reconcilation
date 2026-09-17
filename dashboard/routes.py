"""HTTP routes and request validation for the local review dashboard."""
import json
import hashlib
import mimetypes
import tempfile
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from reconciliation.duplicate_workflow import fingerprint
from reconciliation.review_settings import save_config
from reconciliation.source_selection import SourceSelection
from reconciliation import development_cache
from dashboard import content_review, development, document_status, office_preview
from dashboard.review import Review, workflow_guide


ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/bank": ("bank.html", "text/html; charset=utf-8"),
          "/bank/": ("bank.html", "text/html; charset=utf-8"),
          "/settings": ("settings.html", "text/html; charset=utf-8"),
          "/settings/": ("settings.html", "text/html; charset=utf-8"),
          "/complete": ("complete.html", "text/html; charset=utf-8"),
          "/complete/": ("complete.html", "text/html; charset=utf-8"),
          "/source": ("source.html", "text/html; charset=utf-8"),
          "/source/": ("source.html", "text/html; charset=utf-8"),
          "/content-review": ("content-review.html", "text/html; charset=utf-8"),
          "/content-review/": ("content-review.html", "text/html; charset=utf-8"),
          "/documents": ("documents.html", "text/html; charset=utf-8"),
          "/documents/": ("documents.html", "text/html; charset=utf-8"),
          "/exact-report": ("exact-report.html", "text/html; charset=utf-8"),
          "/exact-report.js": ("exact-report.js", "text/javascript"),
          "/app.js": ("app.js", "text/javascript"),
          "/bank.js": ("bank.js", "text/javascript"),
          "/settings.js": ("settings.js", "text/javascript"),
          "/complete.js": ("complete.js", "text/javascript"),
          "/common.js": ("common.js", "text/javascript"),
          "/source.js": ("source.js", "text/javascript"),
          "/content-review.js": ("content-review.js", "text/javascript"),
          "/documents.js": ("documents.js", "text/javascript"),
          "/documents.css": ("documents.css", "text/css"),
          "/office-view.js": ("office-view.js", "text/javascript"),
          "/style.css": ("style.css", "text/css")}

def handler_for(review, token, sources=None):
    """Serve the active review and local source-folder selection."""
    sources = sources or SourceSelection(review.manifest_path.parent, review.data)
    review_ref = {"current": review}
    server_lock = threading.RLock()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, mime="application/json; charset=utf-8", etag=None):
            """Send a response with consistent local-dashboard security headers."""
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            if etag and self.headers.get("If-None-Match") == etag:
                status, body = 304, b""
            self.send_response(status)
            self.send_header("Content-Type", mime)
            if status != 304:
                self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, no-cache" if etag else "no-store")
            if etag:
                self.send_header("ETag", etag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def local_host(self):
            """Accept only the loopback hostnames used by the dashboard."""
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            """Read review state, previews, or an explicitly allowed static asset."""
            review = review_ref["current"]
            if not self.local_host():
                self.reply(403, {"error": "Local access only"})
                return
            query = urlparse(self.path)
            if review is None and query.path not in {"/documents", "/documents/", "/documents.js", "/documents.css", "/api/document-status", "/source", "/source/", "/source.js", "/bank", "/bank/", "/bank.js", "/common.js", "/style.css", "/api/development-mode", "/api/source", "/api/source/browse", "/api/source/preview", "/api/workspace", "/api/session", "/api/bank-statement", "/api/workflow-checks"}:
                self.send_response(302)
                self.send_header("Location", "/source")
                self.end_headers()
                return
            params = parse_qs(query.query)
            try:
                if query.path in ASSETS:
                    name, mime = ASSETS[query.path]
                    if name == "index.html" and review and review.manifest.get("Mode") == "exact_report":
                        name = "exact-report.html"
                    body = (Path(__file__).parent / "static" / name).read_bytes()
                    self.reply(200, body, mime, '"' + hashlib.sha256(body).hexdigest() + '"')
                    return
                if query.path == "/api/session":
                    self.reply(200, {"token": token})
                    return
                with server_lock:
                    if query.path == "/api/state":
                        self.reply(200, {**review.snapshot(), "token": token})
                    elif query.path == "/api/workspace":
                        self.reply(200, review.workspace() if review else {"name": "No active review", "period": "Choose a source folder"})
                    elif query.path == "/api/workflow-checks":
                        self.reply(200, workflow_guide(review))
                    elif query.path == "/api/config":
                        self.reply(200, review.settings())
                    elif query.path == "/api/development-mode":
                        self.reply(200, development_cache.mode())
                    elif query.path == "/api/development-decisions":
                        self.reply(200, development.snapshot(review))
                    elif query.path == "/api/source":
                        selected = sources.selected()
                        bank = sources.selected_bank()
                        self.reply(200, {"active": str(review.root) if review else None,
                                         "selected": sources.inspect(selected) if selected else None,
                                         "bank": sources.inspect_bank(bank) if bank else None})
                    elif query.path == "/api/source/browse":
                        self.reply(200, sources.browse(params.get("path", [None])[0],
                                                       params.get("kind", ["folder"])[0] == "bank"))
                    elif query.path == "/api/source/preview":
                        self.reply(200, sources.preview())
                    elif query.path == "/api/completion":
                        self.reply(200, review.completion())
                    elif query.path == "/api/content-review":
                        self.reply(200, content_review.snapshot(review))
                    elif query.path == "/api/document-status":
                        self.reply(200, document_status.snapshot(review))
                    elif query.path == "/api/content-file":
                        path = content_review.source(review, params["id"][0])
                        self.reply(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                    elif query.path == "/api/content-image":
                        path = content_review.image(review, params["id"][0], int(params["unit"][0]))
                        self.reply(200, path.read_bytes(), "image/png")
                    elif query.path == "/api/bank-statement":
                        self.reply(200, review.bank_statement() if review else
                                   {"available": False, "transactions": [], "workbook_available": False})
                    elif query.path == "/api/bank-export-defaults":
                        self.reply(200, review.export_defaults())
                    elif query.path == "/api/bank-workbook":
                        workbook = review.manifest_path.parent / "bank-output" / "answer_statement_bank_only.xlsx"
                        self.reply(200, workbook.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    elif query.path == "/api/document":
                        self.reply(200, office_preview.describe(content_review.source(review, params["content_id"][0]))
                                   if "content_id" in params else review.document(params["id"][0]))
                    elif query.path == "/api/office-view":
                        path = (content_review.source(review, params["content_id"][0])
                                if "content_id" in params else review.file_path(params["id"][0]))
                        self.reply(200, office_preview.page(path, int(params.get("page", ["0"])[0])))
                    elif query.path in {"/api/file", "/api/preview"}:
                        file_id = params["id"][0]
                        path = review.file_path(file_id)
                        if query.path == "/api/file":
                            self.reply(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                        elif path.suffix.lower() == ".pdf":
                            import pymupdf
                            with pymupdf.open(path) as pdf:
                                page = int(params.get("page", ["0"])[0])
                                self.reply(200, pdf[page].get_pixmap(dpi=110, alpha=False).tobytes("png"), "image/png")
                        else:
                            document = review.document(file_id)
                            if document["kind"] == "office":
                                units = json.loads((review.data / "previews" / fingerprint(path) / "units.json").read_text(encoding="utf-8"))
                                path = Path(units[int(params.get("page", ["0"])[0])]["image"])
                            self.reply(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "image/png")
                    else:
                        self.reply(404, {"error": "File or page not found"})
            except (KeyError, IndexError, FileNotFoundError):
                self.reply(404, {"error": "File or page not found"})
            except Exception as error:
                self.reply(400, {"error": str(error)})

        def do_POST(self):
            # Token and Origin checks prevent another website from making file choices.
            review = review_ref["current"]
            origin = self.headers.get("Origin")
            allowed = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            if not self.local_host() or self.headers.get("X-Review-Token") != token or (origin and origin not in allowed):
                self.reply(403, {"error": "Refresh the dashboard before making changes"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(length))
                with server_lock:
                    if self.path.startswith("/api/development/") and not development_cache.mode()["enabled"]:
                        raise ValueError("Enable Development / testing mode in Settings first")
                    if self.path == "/api/development-mode":
                        if review and content_review.execution_status(review)["running"]:
                            raise ValueError("Stop the current review before changing development mode")
                        mode = development_cache.set_mode(body["enabled"])
                        if mode["enabled"] and review:
                            development.seed(review)
                        self.reply(200, mode)
                        return
                    if self.path == "/api/keep":
                        review.keep(body["group"], body["id"])
                    elif self.path == "/api/undo":
                        review.undo(body["group"])
                    elif self.path == "/api/validate":
                        problems = check(review.root, review.manifest, review.manifest_path)
                        self.reply(200, {"passed": not problems, "problems": problems})
                        return
                    elif self.path == "/api/config":
                        save_config(review.config_path, body["config"], body["revision"])
                        self.reply(200, review.settings())
                        return
                    elif self.path == "/api/development/remember":
                        self.reply(200, development.remember(review))
                        return
                    elif self.path == "/api/development/apply":
                        self.reply(200, development.apply(review, body["reviewer"]))
                        return
                    elif self.path == "/api/content/prepare":
                        self.reply(200, content_review.prepare(review))
                        return
                    elif self.path == "/api/content/run":
                        self.reply(200, content_review.start(review))
                        return
                    elif self.path == "/api/content/stop":
                        self.reply(200, content_review.stop(review))
                        return
                    elif self.path == "/api/content/decide":
                        self.reply(200, content_review.decide(review, body["pair"], body["verdict"],
                                                             body["reviewer"], body["reason"]))
                        return
                    elif self.path == "/api/content/undo":
                        self.reply(200, content_review.undo(review, body["pair"],
                                                           body["reviewer"], body["reason"]))
                        return
                    elif self.path == "/api/source/select":
                        self.reply(200, {"selected": sources.save(body["path"])})
                        return
                    elif self.path == "/api/source/start":
                        if not isinstance(body.get("preview"), str) or not body["preview"]:
                            raise ValueError("Check the folder to preview exact duplicates first")
                        manifest, data = sources.start(body["preview"])
                        next_review = Review(manifest, data)
                        sources.activate(manifest)
                        review_ref["current"] = next_review
                        self.reply(200, {"active": str(next_review.root), "groups": len(next_review.groups)})
                        return
                    elif self.path == "/api/source/bank-select":
                        self.reply(200, {"bank": sources.save_bank(body["path"])})
                        return
                    elif self.path == "/api/source/bank-prepare":
                        if review is None:
                            raise ValueError("Create a supporting-document review first")
                        self.reply(200, sources.prepare_bank(review.manifest_path, body["year"]))
                        return
                    elif self.path == "/api/bank-export":
                        if review is None:
                            raise ValueError("Choose an active review first")
                        from reconciliation.bank_excel import export
                        master = review.manifest_path.parent / "bank-output" / "master_statement.csv"
                        with tempfile.TemporaryDirectory() as temporary:
                            output = export(master, body["company"],
                                            Path(temporary) / "answer_statement_bank_only.xlsx")
                            development_cache.capture(review.manifest_path, "bank-export", [output])
                            self.reply(200, output.read_bytes(),
                                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        return
                    else:
                        raise ValueError("Unknown action")
                    self.reply(200, review.snapshot())
            except Exception as error:
                self.reply(400, {"error": str(error)})

        def log_message(self, *args):
            """Suppress routine HTTP access logging."""
            pass
    return Handler
