"""Validated settings shared by the dashboard and document-review pipeline."""
import hashlib
import json
import os
from pathlib import Path
from reconciliation.paths import WORKSPACE

CONFIG_PATH = WORKSPACE / "config" / "review_config.json"
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULTS = {"pdf_whole_document_max_pages": 5, "pdf_mode": "vision", "pictures_enabled": True, "codex_enabled": True,
            "max_calls": 1000, "max_parallel": 4, "model": DEFAULT_MODEL, "reasoning": "default", "stages": {}}
STAGES = ("pdf", "images", "excel", "word", "comparison")


def config_for_manifest(manifest):
    """Use shared settings for managed reviews while preserving existing legacy overrides."""
    parent = Path(manifest).resolve().parent
    workspace = CONFIG_PATH.parent.parent
    local = parent / "review_config.json"
    if parent == workspace or (parent.is_relative_to(workspace / "duplicated/projects") and not local.is_file()):
        return CONFIG_PATH
    return local


def model_catalog():
    # Read capability metadata from Codex's own cache; do not guess model identifiers.
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
    # Reject typos and wrong types instead of silently ignoring a switch.
    required = {"pdf_mode", "pictures_enabled", "codex_enabled", "max_calls"}
    if not isinstance(config, dict) or not required <= set(config) or set(config) - set(DEFAULTS):
        raise ValueError("Settings contain missing or unknown fields")
    config = {**DEFAULTS, **config}
    if type(config["pdf_whole_document_max_pages"]) is not int or not 1 <= config["pdf_whole_document_max_pages"] <= 40:
        raise ValueError("Whole-document PDF page limit must be an integer between 1 and 40")
    if config["pdf_mode"] not in ("text_only", "auto", "vision", "hybrid", "compare"):
        raise ValueError("Unknown PDF processing mode")
    if config["pdf_mode"] in ("hybrid", "compare") and not config["pictures_enabled"]:
        raise ValueError("PDF fallback and comparison require pictures")
    if any(type(config[key]) is not bool for key in ("pictures_enabled", "codex_enabled")):
        raise ValueError("Picture and Codex switches must be true or false")
    if type(config["max_calls"]) is not int or not 1 <= config["max_calls"] <= 1000:
        raise ValueError("Call limit must be an integer between 1 and 1000")
    if type(config["max_parallel"]) is not int or not 1 <= config["max_parallel"] <= 8:
        raise ValueError("Parallel requests must be an integer between 1 and 8")
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
    # A missing file uses documented defaults; malformed files fail closed.
    return validate(json.loads(Path(path).read_text(encoding="utf-8-sig"))) if path and Path(path).exists() else dict(DEFAULTS)


def content_settings(config):
    # Execution switches do not invalidate already extracted evidence.
    return {key: config[key] for key in ("pdf_mode", "pictures_enabled")}


def model_settings(config):
    return {key: config.get(key, DEFAULTS[key]) for key in ("model", "reasoning", "stages")}


def stage_settings(config):
    # Older configurations retain their shared model until stage choices are saved.
    fallback = {key: config.get(key, DEFAULTS[key]) for key in ("model", "reasoning")}
    return {stage: dict(config.get("stages", {}).get(stage, fallback)) for stage in STAGES}


def document_stage(path):
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
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def save_config(path, config, expected_revision):
    # Refuse stale browser saves and replace the JSON atomically.
    config = validate(config)
    if config["pdf_mode"] in ("hybrid", "compare"):
        from reconciliation.development_cache import mode
        if not mode()["enabled"]:
            raise ValueError("Enable development mode before selecting experimental PDF processing")
    if expected_revision != revision(load_config(path)):
        raise ValueError("Settings changed elsewhere. Reload the dashboard before saving")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return config
