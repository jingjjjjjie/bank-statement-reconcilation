"""Cached Excel print previews; these PDFs are never extraction or matching inputs."""
import hashlib
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from threading import Lock

import pymupdf

LOCKS = [Lock() for _ in range(16)]


@lru_cache(maxsize=1)
def converter():
    """Identify the installed renderer so upgrades invalidate preview caches."""
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise ValueError("Excel PDF preview requires LibreOffice. Open the original workbook.")
    result = subprocess.run([executable, "--version"], capture_output=True, timeout=15, check=True)
    return executable, result.stdout


def convert_excel_to_pdf(source):
    """Convert an immutable copy once per source hash and renderer version."""
    source = Path(source)
    if source.suffix.lower() != ".xlsx":
        raise ValueError("Excel preview requires an XLSX workbook")
    executable, version = converter()
    data = source.read_bytes()
    key = hashlib.sha256(b"excel-print-v1\0" + version + data).hexdigest()
    cache = Path(os.environ.get("EXCEL_PREVIEW_CACHE", Path(__file__).parent / ".data/excel-pdf"))
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (key + ".pdf")
    with LOCKS[int(key[:2], 16) % len(LOCKS)]:
        if target.is_file():
            try:
                with pymupdf.open(target) as document:
                    if len(document) and not document.needs_pass:
                        return target
            except (RuntimeError, ValueError):
                pass
        with tempfile.TemporaryDirectory(prefix="excel-", dir=cache) as temporary:
            folder = Path(temporary)
            original = folder / "workbook.xlsx"
            original.write_bytes(data)
            profile = folder / "profile"
            user = profile / "user"
            user.mkdir(parents=True)
            (user / "registrymodifications.xcu").write_text(
                '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
                '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
                '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
                '</item></oor:items>', encoding="utf-8")
            try:
                result = subprocess.run([executable, "-env:UserInstallation=" + profile.resolve().as_uri(),
                    "--headless", "--convert-to", "pdf:calc_pdf_Export", "--outdir", str(folder),
                    str(original)], capture_output=True, timeout=90)
            except subprocess.TimeoutExpired as error:
                raise ValueError("Excel preview conversion timed out. Open the original workbook or retry.") from error
            output = folder / "workbook.pdf"
            if result.returncode or not output.is_file():
                raise ValueError("Excel preview conversion failed. Open the original workbook or retry.")
            with pymupdf.open(output) as document:
                if not len(document) or document.needs_pass:
                    raise ValueError("Excel preview conversion produced no readable pages")
            output.replace(target)
    return target
