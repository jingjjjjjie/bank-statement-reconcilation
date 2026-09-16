"""Select a local supporting folder and create an isolated review when requested."""
import base64
import hashlib
import json
import subprocess
from pathlib import Path

from duplicate_workflow import fingerprint, organize, supporting_files


def _choose_path(dialog_type):
    """Open a native Windows picker without requiring Tk in the Python runtime."""
    setup = ("$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
             "$dialog.Description = 'Select supporting documents folder'; "
             "$dialog.ShowNewFolderButton = $false") if dialog_type == "folder" else (
             "$dialog = New-Object System.Windows.Forms.OpenFileDialog; "
             "$dialog.Title = 'Select bank statement PDF'; "
             "$dialog.Filter = 'PDF files (*.pdf)|*.pdf'; "
             "$dialog.CheckFileExists = $true")
    selected = "$dialog.SelectedPath" if dialog_type == "folder" else "$dialog.FileName"
    script = ("Add-Type -AssemblyName System.Windows.Forms; " + setup + "; "
              "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
              f"[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes({selected})) }}")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-STA", "-WindowStyle", "Hidden",
                             "-Command", script], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=False)
    if result.returncode:
        raise RuntimeError("Windows folder picker failed: " + result.stderr.strip())
    return base64.b64decode(result.stdout.strip()).decode("utf-16-le") if result.stdout.strip() else ""


def choose_folder():
    """Open the system folder picker on the computer running the dashboard."""
    return _choose_path("folder")


def choose_bank_pdf():
    """Open the system file picker for a bank-statement PDF."""
    return _choose_path("file")


class SourceSelection:
    """Persist a pending source separately from the active review."""

    def __init__(self, workspace, data):
        """Keep new reviews beneath the workspace's duplicated directory."""
        self.workspace = Path(workspace).resolve()
        self.data = Path(data).resolve()
        self.selection = self.data / "source-selection.json"
        self.bank_selection = self.data / "bank-selection.json"
        self.active = self.data / "active-review.json"

    def selected(self):
        """Return the saved pending folder, if one was chosen."""
        if not self.selection.exists():
            return None
        return Path(json.loads(self.selection.read_text(encoding="utf-8"))["path"])

    def inspect(self, path):
        """Validate and count a source without moving or uploading files."""
        source = Path(path).expanduser().resolve(strict=True)
        if not source.is_dir():
            raise ValueError("Select a folder")
        if self.workspace.is_relative_to(source) or source.is_relative_to(self.workspace / "duplicated"):
            raise ValueError("Select a supporting folder outside the review output tree")
        files = supporting_files(source)
        return {"path": str(source), "files": len(files)}

    def save(self, path):
        """Save a validated choice without changing the active review."""
        result = self.inspect(path)
        self.data.mkdir(parents=True, exist_ok=True)
        self.selection.write_text(json.dumps({"path": result["path"]}), encoding="utf-8")
        return result

    def selected_bank(self):
        """Return the saved bank PDF path, if one was chosen."""
        if not self.bank_selection.exists():
            return None
        return Path(json.loads(self.bank_selection.read_text(encoding="utf-8"))["path"])

    def inspect_bank(self, path):
        """Validate a local bank PDF without reading transactions yet."""
        source = Path(path).expanduser().resolve(strict=True)
        if not source.is_file() or source.suffix.lower() != ".pdf":
            raise ValueError("Select a PDF file")
        return {"path": str(source), "bytes": source.stat().st_size}

    def save_bank(self, path):
        """Save a bank PDF choice without extracting or overwriting a master."""
        result = self.inspect_bank(path)
        self.data.mkdir(parents=True, exist_ok=True)
        self.bank_selection.write_text(json.dumps({"path": result["path"]}), encoding="utf-8")
        return result

    def prepare_bank(self, manifest, year):
        """Extract the selected PDF after an explicit request and protect existing data."""
        import csv
        from bank_statement import extract, write_master

        source = self.selected_bank()
        if source is None:
            raise ValueError("Choose a bank statement PDF first")
        self.inspect_bank(source)
        if not isinstance(year, int) or not 1900 <= year <= 2100:
            raise ValueError("Enter a valid statement year")
        output = Path(manifest).parent / "bank-output" / "master_statement.csv"
        digest = fingerprint(source).lower()
        if output.exists():
            with output.open(newline="", encoding="utf-8-sig") as stream:
                row = next(csv.DictReader(stream), None)
            if row and row.get("source_sha256") == digest and row.get("year_supplied") == str(year):
                return {"path": str(output), "existing": True}
            raise ValueError("This review already has a different bank master; existing data was not replaced")
        result = extract(source, year)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_master(result, output)
        return {"path": str(output), "existing": False}

    def start(self):
        """Initialize or reopen the selected folder's isolated duplicate review."""
        source = self.selected()
        if source is None:
            raise ValueError("Choose a supporting folder first")
        self.inspect(source)
        name = hashlib.sha256(str(source).casefold().encode()).hexdigest()[:16]
        project = self.workspace / "duplicated" / "projects" / name
        project.mkdir(parents=True, exist_ok=True)
        manifest = project / "duplicate-manifest.json"
        if not manifest.exists():
            organize(source, manifest)
        else:
            saved = json.loads(manifest.read_text(encoding="utf-8-sig"))
            if Path(saved["SupportingRoot"]).resolve() != source:
                raise ValueError("Existing review belongs to another source folder")
        return manifest, project / "dashboard-data"

    def activate(self, manifest):
        """Remember the validated review for the next dashboard restart."""
        self.active.write_text(json.dumps({"manifest": str(manifest)}), encoding="utf-8")

    def active_manifest(self, default):
        """Restore an active project only when its manifest is in this workspace."""
        if not self.active.exists():
            return Path(default)
        manifest = Path(json.loads(self.active.read_text(encoding="utf-8"))["manifest"]).resolve()
        if not manifest.is_relative_to(self.workspace / "duplicated" / "projects") or not manifest.is_file():
            raise ValueError("Saved active review path is invalid")
        return manifest
