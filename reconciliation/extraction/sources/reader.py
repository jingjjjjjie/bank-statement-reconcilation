"""Split a supporting document into ordered review units (pages, sheets, images, text parts).

Each unit is a `records.Unit`: a label, its native text and, when pictures are on,
a rendered JPEG the model can look at. The source file is never modified.

To support a new file type, write `reader(path, config, units)` that calls
`units.add(...)` once per unit, and add it to `READERS` at the bottom of this file.
"""

import io
import json
import zipfile
from xml.etree import ElementTree as ET

import openpyxl
import pymupdf
from PIL import Image, ImageOps, ImageSequence

from reconciliation.core.settings import DEFAULTS, validate
from reconciliation.extraction.sources.pdf_routing import MODES, inspect_page

#: Long text is split into parts of this many characters so no part exceeds one model request.
TEXT_PART_CHARS = 12000
#: Rendered pages and pictures are downscaled to fit this square (pixels) before saving.
MAX_IMAGE_SIDE = 2400
#: JPEG quality for saved unit images; about half the size of PNG with no visible loss on receipts.
JPEG_QUALITY = 90
#: Resolution for rendering PDF pages.
PDF_RENDER_DPI = 150
#: A PDF page with fewer letters/digits than this is treated as a scan with no usable text.
SPARSE_PAGE_MIN_CHARS = 20


class UnitWriter:
    """Collect units for one document and save their images into `output`."""

    def __init__(self, output):
        """Start an empty unit list writing images under `output`."""
        self.output = output
        self.units = []

    def add(self, label, text="", image=None, limitation="", blocked="", pdf_probe=None, whole_text=False):
        """Append one unit, splitting long text into parts unless `whole_text` or a PDF probe is given.

        Args:
            label: Human location such as "page 2"; parts get " / part N".
            text: Native text; may be empty for pictures.
            image: PIL image to save as the unit's picture (first part only, except PDF probes).
            limitation: What this unit cannot show, for the reviewer.
            blocked: Non-empty reason the unit cannot be reviewed yet.
            pdf_probe: Native-text layout evidence used by experimental PDF modes.
            whole_text: Keep text in one unit (for spreadsheets, whose rows belong together).
        """
        keep_whole = whole_text or pdf_probe is not None
        chunks = (
            [text]
            if keep_whole
            else [text[i : i + TEXT_PART_CHARS] for i in range(0, len(text), TEXT_PART_CHARS)] or [""]
        )
        for part, chunk in enumerate(chunks, 1):
            unit = {
                "label": label if whole_text else f"{label} / part {part}",
                "text": chunk,
                "image": None,
                "limitation": limitation,
                "blocked": blocked,
            }
            if pdf_probe is not None:
                unit["pdf_probe"] = pdf_probe
            if image is not None and (part == 1 or pdf_probe is not None):
                unit["image"] = self._save_image(image)
            self.units.append(unit)

    def _save_image(self, image):
        """Save an upright, downscaled JPEG for the next unit and return its absolute path."""
        target = self.output / f"unit-{len(self.units) + 1:04d}.jpg"
        picture = ImageOps.exif_transpose(image).convert("RGB")
        picture.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        picture.save(target, quality=JPEG_QUALITY)
        return str(target.resolve())


def extract(path, output, config=None):
    """Return the file's ordered units, writing unit images into `output`.

    Args:
        path: Supporting document to read.
        output: Folder for rendered unit images (created if missing).
        config: Review settings; defaults to `core.settings.DEFAULTS`.

    Raises:
        ValueError: Unsupported type, encrypted PDF, unrenderable embedded object, or nothing readable.
    """
    output.mkdir(parents=True, exist_ok=True)
    config = validate(config if config is not None else dict(DEFAULTS))
    suffix = path.suffix.lower()
    if suffix not in READERS:
        raise ValueError(f"Unsupported file type: {suffix}")
    writer = UnitWriter(output)
    for reader in READERS[suffix]:
        reader(path, config, writer)
    if not writer.units:
        raise ValueError("No readable units extracted")
    return writer.units


def read_pdf(path, config, units):
    """Add one unit per page: native text, plus a rendered picture when the PDF mode asks for it."""
    mode = config["pdf_mode"]
    experimental = mode in MODES
    with pymupdf.open(path) as document:
        if document.needs_pass:
            raise ValueError("Encrypted PDF requires a password")
        for number, page in enumerate(document, 1):
            text = page.get_text()
            sparse = sum(ch.isalnum() for ch in text) < SPARSE_PAGE_MIN_CHARS
            needs_picture = experimental or mode == "vision" or (mode == "auto" and sparse)
            picture, blocked = None, ""
            if needs_picture and config["pictures_enabled"]:
                pixmap = page.get_pixmap(dpi=PDF_RENDER_DPI, alpha=False)
                picture = Image.open(io.BytesIO(pixmap.tobytes("png")))
            elif needs_picture:
                blocked = "PDF vision requested but picture processing is off"
            elif sparse:
                blocked = "PDF page has insufficient extractable text; enable PDF fallback/full vision and pictures"
            limitation = (
                "" if picture else "PDF text only: images, handwriting, signatures and visual layout were not inspected"
            )
            units.add(
                f"page {number}",
                text,
                picture,
                limitation,
                blocked,
                pdf_probe=inspect_page(page) if experimental else None,
            )


def read_image(path, config, units):
    """Add one unit per image frame (multi-page TIFFs have several), or a blocked unit if pictures are off."""
    if not config["pictures_enabled"]:
        units.add("image", blocked="Picture processing is off; this document has not been reviewed")
        return
    with Image.open(path) as picture:
        for number, frame in enumerate(ImageSequence.Iterator(picture), 1):
            units.add(f"image {number}", image=frame.copy())


def read_excel(path, config, units):
    """Add one unit per sheet (including hidden ones) with every cell's formula and cached value."""
    formulas = openpyxl.load_workbook(path, read_only=True, data_only=False)
    values = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in formulas:
            rows = []
            for row, cached in zip(sheet.iter_rows(), values[sheet.title].iter_rows()):
                cells = []
                for cell, value in zip(row, cached):
                    if cell.value is not None:
                        content = {"value": str(cell.value)}
                        if cell.data_type == "f":
                            content["cached"] = str(value.value)
                        cells.append(f"{cell.coordinate}={json.dumps(content, ensure_ascii=False)}")
                if cells:
                    rows.append(" | ".join(cells))
            # Headings, cells and totals of one worksheet stay together in one unit.
            units.add(f"sheet {sheet.title} ({sheet.sheet_state})", "\n".join(rows), whole_text=True)
    finally:
        formulas.close()
        values.close()


def read_word(path, config, units):
    """Add the text of each Word XML part in document order; layout is not reconstructed."""
    with zipfile.ZipFile(path) as package:
        for name in sorted(package.namelist()):
            if name.startswith("word/") and name.endswith(".xml"):
                tree = ET.fromstring(package.read(name))
                text = "\n".join(node.text or "" for node in tree.iter() if node.tag.endswith("}t"))
                if text.strip():
                    units.add(name, text)


def read_office_pictures(path, config, units):
    """Add pictures embedded in an Office file; reject embedded objects that need manual rendering."""
    with zipfile.ZipFile(path) as package:
        for name in sorted(package.namelist()):
            if "/embeddings/" in name or "/charts/" in name and name.endswith(".xml"):
                raise ValueError(f"Embedded object needs manual rendering: {name}")
            if "/media/" in name and not name.endswith("/"):
                if config["pictures_enabled"]:
                    with Image.open(io.BytesIO(package.read(name))) as picture:
                        units.add(name, image=picture)
                else:
                    units.add(name, blocked="Embedded picture was not reviewed because picture processing is off")


IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp")
#: File suffix -> readers run in order. Add a row here to support a new type.
READERS = {
    ".pdf": [read_pdf],
    **{suffix: [read_image] for suffix in IMAGE_SUFFIXES},
    ".xlsx": [read_excel, read_office_pictures],
    ".docx": [read_word, read_office_pictures],
}
SUPPORTED_SUFFIXES = frozenset(READERS)
