"""Validated settings shared by the dashboard and document-review pipeline."""
import hashlib
import json
import os
from pathlib import Path

from reconciliation.core.paths import WORKSPACE

CONFIG_PATH = WORKSPACE / "config" / "review_config.json"
DEFAULT_MODEL = "gpt-6-sol"
DEFAULTS = {"pdf_whole_document_max_pages": 5, "pdf_mode": "vision", "pictures_enabled": True, "codex_enabled": True,
            "max_calls": 1000, "max_parallel": 4, "model": DEFAULT_MODEL, "reasoning": "default", "stages": {}}
STAGES = ("pdf", "images", "excel", "word", "comparison")

#: Allowed ranges for numeric settings, as (lowest, highest) inclusive.
WHOLE_PDF_PAGES_RANGE = (1, 40)
MAX_CALLS_RANGE = (1, 1000)
MAX_PARALLEL_RANGE = (1, 8)
PDF_MODES = ("text_only", "auto", "vision", "hybrid", "compare")


def config_for_manifest(manifest):
    """Use shared settings for managed reviews while preserving existing legacy overrides."""
    parent = Path(manifest).resolve().parent
    workspace = CONFIG_PATH.parent.parent
    local = parent / "review_config.json"
    if parent == workspace or (parent.is_relative_to(workspace / "duplicated/projects") and not local.is_file()):
        return CONFIG_PATH
    return local


def model_catalog():
    """List models from Codex's own catalog cache with their reasoning levels and vision support."""
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    try:
        catalog = json.loads((home / "models_cache.json").read_text(encoding="utf-8"))
        return [{"id": m["slug"], "name": m.get("display_name", m["slug"]),
                 "reasoning": [r["effort"] for r in m.get("supported_reasoning_levels", [])],
                 "vision": "image" in m.get("input_modalities", [])}
                for m in catalog["models"] if m.get("visibility") == "list"]
    except (OSError, ValueError, KeyError):
        return []


def validate(config):
    """Return a complete, checked settings dict; raise ValueError on unknown keys, wrong types or out-of-range values."""
    required = {"pdf_mode", "pictures_enabled", "codex_enabled", "max_calls"}
    if not isinstance(config, dict) or not required <= set(config) or set(config) - set(DEFAULTS):
        raise ValueError("Settings contain missing or unknown fields")
    config = {**DEFAULTS, **config}
    if type(config["pdf_whole_document_max_pages"]) is not int or not in_range(config["pdf_whole_document_max_pages"], WHOLE_PDF_PAGES_RANGE):
        raise ValueError("Whole-document PDF page limit must be an integer between %d and %d" % WHOLE_PDF_PAGES_RANGE)
    if config["pdf_mode"] not in PDF_MODES:
        raise ValueError("Unknown PDF processing mode")
    if config["pdf_mode"] in ("hybrid", "compare") and not config["pictures_enabled"]:
        raise ValueError("PDF fallback and comparison require pictures")
    if any(type(config[key]) is not bool for key in ("pictures_enabled", "codex_enabled")):
        raise ValueError("Picture and Codex switches must be true or false")
    if type(config["max_calls"]) is not int or not in_range(config["max_calls"], MAX_CALLS_RANGE):
        raise ValueError("Call limit must be an integer between %d and %d" % MAX_CALLS_RANGE)
    if type(config["max_parallel"]) is not int or not in_range(config["max_parallel"], MAX_PARALLEL_RANGE):
        raise ValueError("Parallel requests must be an integer between %d and %d" % MAX_PARALLEL_RANGE)
    if not isinstance(config["model"], str) or not isinstance(config["reasoning"], str):
        raise ValueError("Model and reasoning must be strings")
    if config["model"]:
        catalog = model_catalog()
        model = next((m for m in catalog if m["id"] == config["model"]), None)
        # Fresh installations can use the project default before Codex caches capabilities.
        uncached_default = (not catalog and config["model"] == DEFAULT_MODEL
                            and config["reasoning"] == "default")
        if not model and not uncached_default:
            raise ValueError("Model is not listed in the local Codex catalog; refresh Codex or choose its default")
        if model:
            if config["reasoning"] != "default" and config["reasoning"] not in model["reasoning"]:
                raise ValueError("Selected reasoning level is not supported by this model")
            if config["pictures_enabled"] and not model["vision"]:
                raise ValueError("Selected model does not support pictures; disable pictures or choose a vision model")
    elif config["reasoning"] != "default":
        raise ValueError("Choose an explicit model before overriding reasoning")
    stages = config["stages"]
    if not isinstance(stages, dict) or set(stages) - set(STAGES):
        raise ValueError("Unknown workflow stage")
    for stage, choice in stages.items():
        if not isinstance(choice, dict) or set(choice) != {"model", "reasoning"}:
            raise ValueError(f"{stage}: model and reasoning are required")
        needs_vision = config["pictures_enabled"] and (stage != "pdf" or config["pdf_mode"] != "text_only")
        try:
            validate({**config, **choice, "pictures_enabled": needs_vision, "stages": {}})
        except ValueError as error:
            raise ValueError(f"{stage}: {error}") from error
    return {**config, "stages": {stage: dict(choice) for stage, choice in stages.items()}}


def load_config(path=None):
    """Load settings from `path`; a missing file gives the defaults, a malformed one raises."""
    return validate(json.loads(Path(path).read_text(encoding="utf-8-sig"))) if path and Path(path).exists() else dict(DEFAULTS)


def content_settings(config):
    """Return only the settings that change extracted evidence (PDF mode, pictures), not run switches."""
    return {key: config[key] for key in ("pdf_mode", "pictures_enabled")}


def model_settings(config):
    """Return the settings that pick models (model, reasoning, per-stage choices)."""
    return {key: config.get(key, DEFAULTS[key]) for key in ("model", "reasoning", "stages")}


def stage_settings(config):
    """Return the model and reasoning for each stage, falling back to the shared model for older configs."""
    fallback = {key: config.get(key, DEFAULTS[key]) for key in ("model", "reasoning")}
    return {stage: dict(config.get("stages", {}).get(stage, fallback)) for stage in STAGES}


def document_stage(path):
    """Return the settings stage used for a file: pdf, excel, word or images."""
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".xlsx":
        return "excel"
    if suffix == ".docx":
        return "word"
    if suffix in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}:
        return "images"
    raise ValueError(f"No review stage for {suffix}")


def revision(config):
    """Return a stable hash of a settings dict, used to detect changes."""
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def save_config(path, config, expected_revision):
    """Validate and save settings atomically; refuse if the file changed since the browser loaded it."""
    config = validate(config)
    if config["pdf_mode"] in ("hybrid", "compare"):
        from reconciliation.core.development_cache import mode
        if not mode()["enabled"]:
            raise ValueError("Enable development mode before selecting experimental PDF processing")
    if expected_revision != revision(load_config(path)):
        raise ValueError("Settings changed elsewhere. Reload the dashboard before saving")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return config


def in_range(value, bounds):
    """True when `value` lies within inclusive `(lowest, highest)` bounds."""
    return bounds[0] <= value <= bounds[1]
