"""Shapes of the JSON records the workflow saves, for readers and type checkers.

These are documentation-only `TypedDict`s: the files stay plain JSON and nothing
is validated at runtime. Model output shapes are JSON Schemas in `reconciliation/extraction/results/schemas.py`
and `prompts/**/*.schema.json`.

Keys:
- document hash: SHA-256 of the original file bytes (hex, upper case).
- unit key: `"<document hash>:<zero-based unit number>"`.
- pair key: two document hashes joined by `:` in sorted order.
"""

from typing import NotRequired, TypedDict


class Unit(TypedDict):
    """One readable part of a document: a PDF page, sheet, image frame or text part."""

    label: str  # Human location, e.g. "page 2" or "sheet Claims (visible)".
    text: str  # Extracted native text; may be empty for pictures.
    image: str | None  # Absolute path of the rendered JPEG, if pictures are on.
    limitation: str  # What this unit could not show (e.g. text-only PDF).
    blocked: str  # Non-empty reason the unit cannot be reviewed yet.
    image_sha256: NotRequired[str]
    pdf_probe: NotRequired[dict]  # Native-text layout evidence for experimental PDF modes.


class Document(TypedDict):
    """One unique source file (exact copies share a record) prepared for extraction."""

    id: str  # Document hash.
    paths: list[str]  # Current locations; the first is read.
    original_paths: list[str]  # Locations recorded in the duplicate manifest.
    units: list[Unit]
    error: str | None  # Preparation failure; the document stays unresolved.
    accepted: bool  # False for unsupported file types.


class Index(TypedDict):
    """`index.json`: the frozen inputs of one review."""

    root: str  # Supporting-documents folder.
    manifest: str  # Exact-duplicate manifest path.
    documents: dict[str, Document]  # Keyed by document hash.
    config: dict  # Review settings at preparation time.
    config_path: str | None


class State(TypedDict):
    """`state.json`: every saved model result and admin decision, checkpointed after each call."""

    index_sha256: str  # Hash of index.json; a mismatch means the review must be recreated.
    units: dict[str, dict]  # Unit key -> extraction result (legacy receipt record).
    assemblies: NotRequired[dict[str, dict]]  # Document hash -> multi-unit receipt assembly.
    decisions: dict[str, dict]  # Pair key -> admin keep/remove verdict from retired duplicate comparison; read-only.
    screens: NotRequired[dict[str, dict]]  # Retired: old duplicate screening rows, left in older files.
    pairs: NotRequired[dict[str, dict]]  # Retired: old duplicate comparisons, left in older files.
    decision_history: NotRequired[list[dict]]
    stage_models: NotRequired[dict[str, dict]]  # Stage -> {"model", "reasoning"} pinned for this review.
    model_config: NotRequired[dict]
    model: str | None  # Legacy single-model field.
