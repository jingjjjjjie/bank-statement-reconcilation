"""Local duplicate-review dashboard. Run with Python; no web framework required."""
import argparse
import hashlib
import json
import mimetypes
import secrets
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))
from duplicate_workflow import check, duplicate_root, fingerprint, supporting_files
from review_settings import load_config, save_config, revision, content_settings, model_settings, model_catalog


def write_json(path, data):
    # Replace state atomically so interrupted writes cannot corrupt the audit log.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Review:
    def __init__(self, manifest_path, data):
        # Only manifest-listed files can be previewed, retained or restored.
        self.manifest_path, self.data = manifest_path.resolve(), data.resolve()
        self.config_path = self.manifest_path.parent / "review_config.json"
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        self.root = Path(self.manifest["SupportingRoot"]).resolve()
        self.duplicates = duplicate_root(self.manifest, self.manifest_path)
        if self.data.is_relative_to(self.root) or self.data.is_relative_to(self.duplicates):
            raise ValueError("Recovery storage must be outside scanned supporting folders")
        self.data.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data / "decisions.json"
        self.state = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else {"actions": [], "manifest": str(self.manifest_path)}
        if self.state.get("manifest", str(self.manifest_path)) != str(self.manifest_path):
            raise ValueError("This recovery folder belongs to another manifest")
        self.records, self.groups = {}, {}
        self.lock = threading.RLock()
        for row in self.manifest["Files"]:
            path = Path(row["OrganizedPath"]).resolve()
            if not path.is_relative_to(self.duplicates) or path.parent.name != row["Group"]:
                raise ValueError("Manifest contains an unexpected organized path")
            file_id = hashlib.sha256(str(path).encode()).hexdigest()[:20]
            self.records[file_id] = {**row, "id": file_id}
            self.groups.setdefault(row["Group"], []).append(file_id)

    def latest(self, group):
        # Keep prior choices in history even after an undo.
        return next((a for a in reversed(self.state["actions"]) if a["group"] == group), None)

    def settings(self):
        # Expose saved settings and whether the prepared inputs need refreshing.
        config = load_config(self.config_path)
        index_path = self.manifest_path.parent / "review" / "index.json"
        refresh = False
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            old = index.get("config", {"pdf_mode": "vision", "pictures_enabled": True})
            refresh = content_settings(config) != content_settings(old)
            state_path = index_path.with_name("state.json")
            if state_path.exists():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("model_config") and model_settings(state["model_config"]) != model_settings(config):
                    refresh = True
        return {"config": config, "revision": revision(config), "requires_refresh": refresh,
                "models": model_catalog()}

    def file_path(self, file_id):
        # Archived copies remain previewable; arbitrary filesystem paths are never accepted.
        record = self.records[file_id]
        current = Path(record["OrganizedPath"])
        if current.is_file():
            return current
        for action in reversed(self.state["actions"]):
            for move in action["moves"]:
                if move["id"] == file_id:
                    archived = Path(move["archive"]).resolve()
                    if not archived.is_relative_to(self.data):
                        raise ValueError("Recovery path escaped dashboard storage")
                    if archived.is_file():
                        return archived
        raise FileNotFoundError("This copy is no longer available")

    def snapshot(self):
        # Verify actual files, not just saved decisions, to show the current review state.
        groups = []
        for name, ids in self.groups.items():
            files, errors = [], []
            folder = self.duplicates / name
            known = {Path(self.records[i]["OrganizedPath"]) for i in ids}
            if not folder.is_dir():
                errors.append("Group folder is missing")
            elif set(supporting_files(folder)) - known:
                errors.append("Unexpected files in this group")
            for file_id in ids:
                record = self.records[file_id]
                present = Path(record["OrganizedPath"]).is_file()
                available, valid, size = False, False, 0
                try:
                    path = self.file_path(file_id)
                    available, size = True, path.stat().st_size
                    valid = fingerprint(path) == record["SHA256"]
                    if not valid:
                        errors.append("A file has changed since duplicate verification")
                except FileNotFoundError:
                    pass
                files.append({"id": file_id, "name": Path(record["OriginalPath"]).name,
                              "original": record["OriginalPath"], "present": present,
                              "available": available, "valid": valid, "size": size})
            count = sum(f["present"] for f in files)
            action = self.latest(name)
            if action and action["status"] in {"moving", "restoring"}:
                errors.append("An interrupted action needs recovery; no further changes allowed")
            if not count:
                errors.append("No retained file in this group")
            groups.append({"id": name, "files": files, "hash": self.records[ids[0]]["SHA256"],
                           "status": "attention" if errors else "reviewed" if count == 1 else "pending",
                           "errors": errors, "can_undo": bool(action and action["status"] == "done"),
                           "kept": action["keep"] if action and action["status"] == "done" else None})
        return {"groups": groups, "folder": str(self.duplicates),
                "reviewed": sum(g["status"] == "reviewed" for g in groups),
                "pending": sum(g["status"] == "pending" for g in groups),
                "attention": sum(g["status"] == "attention" for g in groups)}

    def keep(self, group, file_id):
        # Save a recovery plan before moving any copies out of the active review folder.
        with self.lock:
            if file_id not in self.groups[group]:
                raise ValueError("Selected file does not belong to this group")
            current = next(g for g in self.snapshot()["groups"] if g["id"] == group)
            if current["errors"]:
                raise ValueError("Resolve this group's file errors before making a choice")
            active = [f["id"] for f in current["files"] if f["present"]]
            if file_id not in active:
                raise ValueError("Choose a copy that is still in the group, or undo first")
            if len(active) == 1:
                return
            action = {"id": secrets.token_hex(8), "group": group, "keep": file_id,
                      "at": datetime.now(timezone.utc).isoformat(), "status": "moving", "moves": []}
            archive = self.data / "recovery" / action["id"]
            archive.mkdir(parents=True)
            for other in active:
                if other != file_id:
                    source = Path(self.records[other]["OrganizedPath"])
                    action["moves"].append({"id": other, "source": str(source), "archive": str(archive / source.name)})
            self.state["actions"].append(action)
            write_json(self.state_path, self.state)
            moved = []
            try:
                for move in action["moves"]:
                    source, target = Path(move["source"]), Path(move["archive"])
                    if not source.resolve().is_relative_to(self.duplicates) or not target.resolve().is_relative_to(self.data):
                        raise ValueError("Move escaped its expected folder")
                    if target.exists() or fingerprint(source) != self.records[move["id"]]["SHA256"]:
                        raise ValueError("File changed during review; no choice applied")
                    source.rename(target)
                    moved.append(move)
                    if fingerprint(target) != self.records[move["id"]]["SHA256"]:
                        raise ValueError("Archived copy changed during review")
                if fingerprint(Path(self.records[file_id]["OrganizedPath"])) != self.records[file_id]["SHA256"]:
                    raise ValueError("Retained copy changed during review")
                action["status"] = "done"
                write_json(self.state_path, self.state)
            except Exception:
                for move in reversed(moved):
                    Path(move["archive"]).rename(move["source"])
                action["status"] = "rolled_back"
                write_json(self.state_path, self.state)
                raise

    def undo(self, group):
        # Restore the original copies only if both the survivor and recovery files are unchanged.
        with self.lock:
            action = self.latest(group)
            if not action or action["status"] != "done":
                raise ValueError("There is no completed dashboard choice to undo")
            current = next(g for g in self.snapshot()["groups"] if g["id"] == group)
            if current["errors"]:
                raise ValueError("Resolve file errors before undo")
            for move in action["moves"]:
                source, archived = Path(move["source"]), Path(move["archive"])
                if not source.resolve().is_relative_to(self.duplicates) or not archived.resolve().is_relative_to(self.data):
                    raise ValueError("Recovery path escaped its expected folder")
                if source.exists() or not archived.is_file() or fingerprint(archived) != self.records[move["id"]]["SHA256"]:
                    raise ValueError("Recovery files changed or original location is occupied")
            restored = []
            action["status"] = "restoring"
            write_json(self.state_path, self.state)
            try:
                for move in action["moves"]:
                    Path(move["archive"]).rename(move["source"])
                    restored.append(move)
                action["status"] = "undone"
                write_json(self.state_path, self.state)
            except Exception:
                for move in reversed(restored):
                    Path(move["source"]).rename(move["archive"])
                action["status"] = "done"
                write_json(self.state_path, self.state)
                raise

    def document(self, file_id):
        # PDFs and images use native previews; Office files use all extracted text/image units.
        path = self.file_path(file_id)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            import pymupdf
            with pymupdf.open(path) as pdf:
                return {"kind": "pdf", "pages": len(pdf)}
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            return {"kind": "image", "pages": 1}
        from document_reader import extract
        cache = self.data / "previews" / fingerprint(path)
        metadata = cache / "units.json"
        if not metadata.exists():
            write_json(metadata, extract(path, cache))
        units = json.loads(metadata.read_text(encoding="utf-8"))
        return {"kind": "office", "pages": len(units), "units": [
            {"label": u["label"], "text": u["text"], "has_image": bool(u["image"])} for u in units]}


def handler_for(review, token):
    # Bind a same-origin local API to a specific review instance.
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, mime="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def local_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self.local_host():
                self.reply(403, {"error": "Local access only"})
                return
            query = urlparse(self.path)
            params = parse_qs(query.query)
            try:
                with review.lock:
                    if query.path == "/api/state":
                        self.reply(200, {**review.snapshot(), "token": token})
                    elif query.path == "/api/session":
                        self.reply(200, {"token": token})
                    elif query.path == "/api/config":
                        self.reply(200, review.settings())
                    elif query.path == "/api/document":
                        self.reply(200, review.document(params["id"][0]))
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
                        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                                  "/settings": ("settings.html", "text/html; charset=utf-8"),
                                  "/settings/": ("settings.html", "text/html; charset=utf-8"),
                                  "/app.js": ("app.js", "text/javascript"),
                                  "/settings.js": ("settings.js", "text/javascript"),
                                  "/common.js": ("common.js", "text/javascript"),
                                  "/style.css": ("style.css", "text/css")}
                        name, mime = assets[query.path]
                        self.reply(200, (Path(__file__).parent / name).read_bytes(), mime)
            except (KeyError, IndexError, FileNotFoundError):
                self.reply(404, {"error": "File or page not found"})
            except Exception as error:
                self.reply(400, {"error": str(error)})

        def do_POST(self):
            # Token and Origin checks prevent another website from making file choices.
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
                with review.lock:
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
                    else:
                        raise ValueError("Unknown action")
                    self.reply(200, review.snapshot())
            except Exception as error:
                self.reply(400, {"error": str(error)})

        def log_message(self, *args):
            pass
    return Handler


def main():
    # Listen on loopback only; launching the dashboard never changes source files.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--manifest", type=Path, default=WORKSPACE / "duplicate-manifest.json")
    parser.add_argument("--data", type=Path, default=Path(__file__).parent / ".data")
    args = parser.parse_args()
    review = Review(args.manifest, args.data)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(review, secrets.token_urlsafe(32)))
    print(f"Dashboard: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
