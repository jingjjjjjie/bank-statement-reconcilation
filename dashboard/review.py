"""Review state, recoverable duplicate decisions, and workflow readiness."""
import csv
import hashlib
import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from reconciliation.duplicate_workflow import check, duplicate_root, fingerprint, supporting_files
from reconciliation.review_settings import (
    DEFAULTS, config_for_manifest, content_settings, load_config, model_catalog, model_settings, revision,
)
from reconciliation.token_usage import summary as token_summary
from dashboard import office_preview


def write_json(path, data):
    # Replace state atomically so interrupted writes cannot corrupt the audit log.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Review:
    """Manage a manifest and its human decisions without HTTP dependencies."""

    def __init__(self, manifest_path, data):
        # Only manifest-listed files can be previewed, retained or restored.
        self.manifest_path, self.data = manifest_path.resolve(), data.resolve()
        self.config_path = config_for_manifest(self.manifest_path)
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
        return {"config": config, "defaults": DEFAULTS, "revision": revision(config), "requires_refresh": refresh,
                "token_usage": token_summary(self.manifest_path.parent / "review" / "token-usage.jsonl"),
                "models": model_catalog()}

    def workspace(self):
        """Name the active source and statement period without fixed customer text."""
        master = self.manifest_path.parent / "bank-output" / "master_statement.csv"
        period = "Bank statement pending"
        if master.is_file():
            with master.open(newline="", encoding="utf-8-sig") as source:
                first = next(csv.DictReader(source), None)
            if first and first.get("date"):
                period = datetime.fromisoformat(first["date"]).strftime("%B %Y")
        is_workspace = self.root.name == "documents" and (self.root.parent / "statement").is_dir()
        name = self.root.parent.name if is_workspace else self.root.name
        return {"name": name, "period": period}

    def export_defaults(self):
        """Suggest the existing company for the reusable bank workbook style."""
        workbook = self.manifest_path.parent / "bank-output" / "answer_statement_bank_only.xlsx"
        company = ""
        if workbook.is_file():
            from openpyxl import load_workbook
            source = load_workbook(workbook, read_only=True)
            try:
                company = source.active["A1"].value or ""
            finally:
                source.close()
        return {"company": company}

    def completion(self):
        """Show final usage only after exact, content, and bank checks pass."""
        from reconciliation.vision_workflow import gate, load

        exact_done = not check(self.root, self.manifest, self.manifest_path)
        content_done = False
        work = self.manifest_path.parent / "review"
        if (work / "index.json").exists():
            try:
                content_done = not gate(*load(work))
            except (OSError, ValueError, KeyError):
                pass
        exact_done = exact_done or content_done
        bank_done = False
        master = self.manifest_path.parent / "bank-output" / "master_statement.csv"
        if content_done and master.exists():
            with master.open(newline="", encoding="utf-8-sig") as source:
                rows = list(csv.DictReader(source))
            bank_done = bool(rows) and all(row.get("balance_checks") == "passed" and
                                           row.get("matching_status") == "matched" for row in rows)
        return {"exact_done": exact_done, "content_done": content_done,
                "bank_done": bank_done, "complete": exact_done and content_done and bank_done,
                "token_usage": token_summary(work / "token-usage.jsonl") if bank_done else None}

    def bank_statement(self):
        """Read the prepared bank master for the dashboard without changing it."""
        master = self.manifest_path.parent / "bank-output" / "master_statement.csv"
        if not master.is_file():
            return {"available": False, "transactions": [], "workbook_available": False}
        with master.open(newline="", encoding="utf-8-sig") as source:
            rows = list(csv.DictReader(source))
        if not rows:
            raise ValueError("Bank master has no transactions")
        fields = ("transaction_id", "date", "page", "direction", "money_in", "money_out",
                  "balance", "counterparty", "counterparty_role", "narration", "matching_status")
        first = rows[0]
        workbook = self.manifest_path.parent / "bank-output" / "answer_statement_bank_only.xlsx"
        return {"available": True, "account": first["account"], "currency": first["currency"],
                "opening_balance": first["opening_balance"], "closing_balance": first["closing_balance"],
                "total_money_in": first["total_money_in"], "total_money_out": first["total_money_out"],
                "count": len(rows), "balance_checks": first["balance_checks"],
                "matched": sum(row["matching_status"] == "matched" for row in rows),
                "workbook_available": workbook.is_file(),
                "transactions": [{key: row[key] for key in fields} for row in rows]}

    def workflow_checks(self):
        """Check saved stage results without changing review files or invoking a model."""
        from reconciliation.vision_workflow import gate, load

        exact = not check(self.root, self.manifest, self.manifest_path)
        work = self.manifest_path.parent / "review"
        content = False
        if exact and (work / "index.json").is_file():
            try:
                content = not gate(*load(work))
            except (OSError, ValueError, KeyError):
                pass
        master = self.manifest_path.parent / "bank-output" / "master_statement.csv"
        bank = False
        if master.is_file():
            try:
                with master.open(newline="", encoding="utf-8-sig") as stream:
                    rows = list(csv.DictReader(stream))
                bank = bool(rows) and all(row.get("balance_checks") == "passed" for row in rows)
            except (OSError, ValueError, KeyError):
                pass
        return exact, content, bank

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

    def group_snapshot(self, name):
        """Verify one exact-copy group before changing it."""
        ids = self.groups[name]
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
        return {"id": name, "files": files, "hash": self.records[ids[0]]["SHA256"],
                "status": "attention" if errors else "reviewed" if self.manifest.get("Mode") == "exact_report" or count == 1 else "pending",
                "errors": errors, "can_undo": bool(action and action["status"] == "done"),
                "kept": action["keep"] if action and action["status"] == "done" else None}

    def snapshot(self):
        """Verify every group for the dashboard summary."""
        groups = [self.group_snapshot(name) for name in self.groups]
        return {"groups": groups, "folder": str(self.duplicates),
                "automatic": self.manifest.get("Mode") == "exact_report",
                "summary": self.manifest.get("Summary", {}),
                "reviewed": sum(g["status"] == "reviewed" for g in groups),
                "pending": sum(g["status"] == "pending" for g in groups),
                "attention": sum(g["status"] == "attention" for g in groups)}

    def keep(self, group, file_id):
        # Save a recovery plan before moving any copies out of the active review folder.
        if self.manifest.get("Mode") == "exact_report":
            raise ValueError("Exact duplicates are reported automatically; no selection is needed")
        with self.lock:
            if file_id not in self.groups[group]:
                raise ValueError("Selected file does not belong to this group")
            current = self.group_snapshot(group)
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
            self.cache_decisions()

    def undo(self, group):
        # Restore the original copies only if both the survivor and recovery files are unchanged.
        if self.manifest.get("Mode") == "exact_report":
            raise ValueError("Automatic exact-duplicate reports have no selection to undo")
        with self.lock:
            action = self.latest(group)
            if not action or action["status"] != "done":
                raise ValueError("There is no completed dashboard choice to undo")
            current = self.group_snapshot(group)
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
            self.cache_decisions()

    def cache_decisions(self):
        """Keep development history outside the review folder when enabled."""
        from dashboard import development
        development.capture(self)

    def document(self, file_id):
        # PDFs and images use native previews; Office files use structured visual pages.
        path = self.file_path(file_id)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            import pymupdf
            with pymupdf.open(path) as pdf:
                return {"kind": "pdf", "pages": len(pdf)}
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            return {"kind": "image", "pages": 1}
        if suffix in {".docx", ".xlsx"}:
            return office_preview.describe(path)
        from reconciliation.document_reader import extract
        cache = self.data / "previews" / fingerprint(path)
        metadata = cache / "units.json"
        if not metadata.exists():
            write_json(metadata, extract(path, cache))
        units = json.loads(metadata.read_text(encoding="utf-8"))
        return {"kind": "office", "pages": len(units), "units": [
            {"label": u["label"], "text": u["text"], "has_image": bool(u["image"])} for u in units]}


def workflow_guide(review):
    """Describe verified stage readiness and the next route for the dashboard."""
    exact, content, bank = review.workflow_checks() if review else (False, False, False)
    complete = False
    if review and exact and content and bank:
        try:
            complete = review.completion()["complete"]
        except (OSError, ValueError, KeyError):
            pass
    stages = [("Workspace", "/", bool(review)),
              ("Exact duplicates", "/review", exact),
              ("Content review", "/content-review" if
               (Path(__file__).parent / "static" / "content-review.html").is_file() else None, content),
              ("Bank extraction", "/bank", bank),
              ("Completion", "/complete", complete)]
    return {"steps": [{"name": name, "href": href, "checked": checked,
                       "next": stages[number + 1][1] if checked and number < len(stages) - 1
                       and all(previous[2] for previous in stages[:number]) else None}
                      for number, (name, href, checked) in enumerate(stages)]}
