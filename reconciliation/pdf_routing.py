"""Conservative PDF routing with auditable evidence and visual fallback."""
import hashlib
import json
import subprocess

from jsonschema import ValidationError, validate

from reconciliation.codex_reviewer import EXTRACTION
from reconciliation.development_cache import mode, write_json
from reconciliation.paths import WORKSPACE
from reconciliation.prompts import load_prompt

MODES = {"hybrid", "compare"}


def inspect_page(page):
    """Keep native word positions and reject risky pages before text inference."""
    words = page.get_text("words", sort=True)
    text = page.get_text()
    reasons = []
    if sum(c.isalnum() for c in text) < 40:
        reasons.append("insufficient_native_text")
    if "\ufffd" in text or any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        reasons.append("garbled_text")
    # Any bitmap may contain a separate receipt: do not guess whether it is a logo.
    if page.get_image_info():
        reasons.append("image_content_or_scan")
    traces = page.get_texttrace()
    if any(t.get("type") == 3 or t.get("opacity", 1) < 1 for t in traces):
        reasons.append("hidden_or_translucent_text")
    if any(tuple(t.get("dir", (1, 0))) != (1, 0) for t in traces):
        reasons.append("rotated_text")
    if len(text) > 12000:
        reasons.append("long_page")
    if len(page.get_drawings()) > 100:
        reasons.append("complex_vector_layout")
    for i, word in enumerate(words):
        box = word[:4]
        if any(min(box[2], other[2]) - max(box[0], other[0]) > 1
               and min(box[3], other[3]) - max(box[1], other[1]) > 1 for other in words[:i]):
            reasons.append("overlapping_text")
            break
    # Exact geometry is intentionally conservative; unrecognized layouts keep vision.
    geometry = [[round(v, 1) for v in w[:4]] for w in words]
    signature = hashlib.sha256(json.dumps([list(page.rect), geometry]).encode()).hexdigest()
    return {"layout": signature, "reasons": reasons,
            "words": [{"text": w[4], "bbox": list(w[:4])} for w in words]}


def approved_layouts():
    """Load locally reviewed layout IDs; an empty allowlist enables no text-only pages."""
    path = WORKSPACE / "config/pdf-layouts.local.json"
    return set(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else set()


def evidence_errors(result, probe):
    """Require unambiguous receipts with source-backed critical values."""
    validate(result, EXTRACTION)
    errors, evidence = [], []
    if not result["readable"] or result["receipt_status"] != "receipt" or result["limitations"]:
        errors.append("uncertain_text_extraction")
    if len(result["receipts"]) != 1:
        errors.append("ambiguous_receipt_boundaries")
    totals = {(m['amount'], m['currency']) for m in result['money']
              if m['role'] in ('grand_total', 'invoice_total')}
    if len(totals) > 1:
        errors.append("conflicting_totals_or_currencies")
    words = probe["words"]
    for index, receipt in enumerate(result["receipts"]):
        if receipt["limitations"] or not receipt["total"] or not receipt["currency"]:
            errors.append("incomplete_receipt")
        values = {"total": receipt["total"], "currency": receipt["currency"]}
        values.update({f"invoice_{n}": v for n, v in enumerate(receipt["invoice_numbers"])})
        for field, value in values.items():
            # Exact token evidence avoids substring matches such as 24.00 in 124.00.
            matches = [w for w in words if w["text"].strip(" :;()") == value]
            if value and not matches:
                errors.append(f"unsupported_{field}")
            evidence.append({"receipt": index, "field": field, "value": value, "matches": matches})
    return sorted(set(errors)), evidence


def critical_fields(result):
    """Compare receipt boundaries and financial identifiers, excluding prose."""
    return [{k: r[k] for k in ("invoice_numbers", "total", "currency")}
            for r in result.get("receipts", [])]


def extract_unit(unit, ask, selected_mode, audit_path, allowlist=None):
    """Try eligible text, fall back on checks, and retain both results durably."""
    if selected_mode not in MODES:
        raise ValueError("Unknown experimental PDF mode")
    if not mode()["enabled"]:
        raise ValueError("Experimental PDF modes require development mode")
    if not unit.get("image"):
        raise ValueError("PDF fallback requires a full-page image; prepare the review again")
    probe = unit.get("pdf_probe", {"reasons": ["missing_page_inspection"], "layout": "", "words": []})
    approved = approved_layouts() if allowlist is None else allowlist
    reasons = list(probe["reasons"])
    if selected_mode == "hybrid" and probe["layout"] not in approved:
        reasons.append("layout_not_validated")
    audit = {"mode": selected_mode, "location": unit["label"], "layout": probe["layout"],
             "reasons": reasons, "status": "started", "text_result": None, "vision_result": None,
             "text_schema_valid": False}
    write_json(audit_path, audit)
    payload = {"location": unit["label"], "text": "" if "long_page" in reasons else unit["text"], "limitation": ""}
    prompt = load_prompt("extraction") + "\n" + json.dumps(payload, ensure_ascii=False)
    try:
        if not reasons:
            try:
                candidate = ask(prompt + "\n" + load_prompt("pdf_text"), EXTRACTION, (), stage="pdf_text")
                audit["text_result"] = candidate
                failures, audit["evidence"] = evidence_errors(candidate, probe)
                audit["text_schema_valid"] = True
                reasons.extend(failures)
            except (ValueError, ValidationError, subprocess.TimeoutExpired) as error:
                reasons.append("text_attempt_failed: " + str(error))
            write_json(audit_path, audit)
        # Compare mode always retains vision; hybrid samples 10% of passing layouts.
        sampled = int(hashlib.sha256(unit["text"].encode()).hexdigest()[:8], 16) % 10 == 0
        use_vision = bool(reasons) or selected_mode == "compare" or sampled
        if use_vision:
            audit["route"] = "vision"
            if sampled and not reasons:
                reasons.append("visual_audit_sample")
            result = ask(prompt, EXTRACTION, [unit["image"]], stage="pdf_vision")
            audit["vision_result"] = result
            if audit["text_schema_valid"]:
                audit["critical_fields_agree"] = critical_fields(result) == critical_fields(audit["text_result"])
                if not audit["critical_fields_agree"]:
                    warning = "Text and vision disagree; verify receipt boundaries and fields against the original."
                    result = {**result, "limitations": [*result["limitations"],
                              warning], "receipts": [{**r, "limitations": [*r["limitations"], warning]}
                                                      for r in result["receipts"]]}
        else:
            audit["route"] = "text"
            result = audit["text_result"]
        audit["status"] = "finished"
        return result
    finally:
        if audit["status"] != "finished":
            audit["status"] = "unresolved"
        write_json(audit_path, audit)
