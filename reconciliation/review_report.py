"""Render the human-readable review report; `report.json` stays the full audit trail."""
import json

MAX_LISTED_PROBLEMS = 100


def render(index, state, problems, usage):
    """Return report.md text for one review.

    Args:
        index: Prepared documents (`records.Index`).
        state: Saved results (`records.State`).
        problems: Outstanding checks from `vision_workflow.gate`.
        usage: Token totals from `token_usage.summary`.
    """
    documents = index["documents"]
    status = "PENDING" if problems else "COMPLETE"
    rows = ["# Document extraction", "", f"Status: {status}",
            f"Documents: {len(documents)}; units read: {len(state['units'])}", ""]
    settings = index.get("config", {"pdf_mode": "vision", "pictures_enabled": True})
    rows += [f"Prepared PDF mode: {settings['pdf_mode']}; pictures: {settings['pictures_enabled']}.",
             f"Stage models used: {json.dumps(state.get('stage_models', {}))}.",
             "Text-only PDF units exclude signatures, handwriting and visual differences; blocked units remain unresolved.", ""]
    rows += _usage_section(usage)
    rows += ["## Outstanding checks", "", f"{len(problems)} unresolved checks.", ""]
    rows += [f"- {p}" for p in problems[:MAX_LISTED_PROBLEMS]]
    if len(problems) > MAX_LISTED_PROBLEMS:
        rows.append("- Full outstanding list is in report.json.")
    return "\n".join(rows)


def _usage_section(usage):
    """List recorded token totals; attempts without reported usage stay excluded, never estimated."""
    totals = usage["totals"]
    return ["## Codex token usage", "",
            f"Recorded attempts: {usage['attempts']}; cache hits: {usage['cache_hits']}; "
            f"attempts with unknown usage: {usage['unknown_attempts']}.",
            f"Reported input: {totals['input_tokens']:,}; cached input: {totals['cached_input_tokens']:,}; "
            f"output: {totals['output_tokens']:,}; reasoning output: {totals['reasoning_output_tokens']:,}.",
            "Totals cover recorded Codex calls only; unknown attempts are excluded.", ""]
