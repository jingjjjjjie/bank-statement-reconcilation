"""Legacy duplicate screening and whole-document comparison stages.

New dashboard and CLI runs are extraction-only and skip these stages; they remain
so older reviews and tools can finish. See `workflow_stages` for the stage contract.
"""
import json

from reconciliation.comparison_policy import route as comparison_route
from reconciliation.prompts import load_prompt
from reconciliation.schemas import COMPARISON, SCREEN
from reconciliation.model_client import MAX_IMAGES, MAX_PROMPT
from reconciliation.workflow_stages import pack

SCREEN_BATCH = 12


def pair_key(left, right):
    """Return the order-independent key for two document hashes."""
    return ":".join(sorted((left, right)))


class DuplicateScreening:
    """Screen document summaries in batches; strong local matches skip straight to comparison."""

    refill = None

    def __init__(self, ctx):
        """Bind the stage to one run."""
        self.ctx = ctx

    def _summaries(self):
        """Summarize every fully readable document from its saved unit extractions."""
        ctx = self.ctx
        ready = [d for d, doc in ctx.documents.items() if doc.get("accepted", True) and not doc["error"] and all(
            ctx.state["units"].get(f"{d}:{n}", {}).get("readable") for n in range(len(doc["units"])))]
        return {d: [{"location": unit["label"], **ctx.state["units"][f"{d}:{n}"]}
                    for n, unit in enumerate(ctx.documents[d]["units"])] for d in ready}

    def jobs(self):
        """Yield one model call per batch of unscreened right-hand documents."""
        ctx = self.ctx
        summaries = self._summaries()
        ready = list(summaries)
        for position, left in enumerate(ready):
            rights = []
            for right in ready[position + 1:]:
                pair = pair_key(left, right)
                if pair in ctx.state["screens"]:
                    continue
                route, reason = comparison_route(summaries[left], summaries[right])
                if route == "direct_compare":
                    ctx.state["screens"][pair] = {"right_id": right, "candidate": True, "reason": reason}
                else:
                    rights.append(right)
            ctx.checkpoint()
            for start in range(0, len(rights), SCREEN_BATCH):
                yield lambda left=left, batch=rights[start:start + SCREEN_BATCH]: self._screen(summaries, left, batch)

    def _screen(self, summaries, left, batch):
        """Screen one batch and reject incomplete model coverage."""
        prompt = load_prompt("legacy/screening") + "\n" + json.dumps(
            {"left": summaries[left], "right": {r: summaries[r] for r in batch}}, ensure_ascii=False)
        if len(prompt) > MAX_PROMPT:
            return left, [{"right_id": r, "candidate": True, "reason": "Summary too large; direct review required"}
                          for r in batch]

        def verify(response):
            """Require exactly one result for each requested document."""
            rows = response["comparisons"]
            if len(rows) != len(batch) or {r["right_id"] for r in rows} != set(batch):
                raise ValueError("Model omitted or repeated a comparison; coverage remains incomplete")

        return left, self.ctx.ask(prompt, SCREEN, verify=verify)["comparisons"]

    def apply(self, result):
        """Save a complete summary batch as its model call finishes."""
        left, rows = result
        for row in rows:
            self.ctx.state["screens"][pair_key(left, row["right_id"])] = row
        self.ctx.checkpoint()


class DocumentComparison:
    """Compare each screened candidate pair using original text and images, not summaries."""

    refill = None

    def __init__(self, ctx):
        """Bind the stage to one run."""
        self.ctx = ctx

    def jobs(self):
        """Yield one comparison per candidate pair without a saved verdict."""
        for pair, screen in self.ctx.state["screens"].items():
            if screen["candidate"] and pair not in self.ctx.state["pairs"]:
                yield lambda pair=pair: self._compare(pair)

    def _compare(self, pair):
        """Compare one pair; oversized pairs are left for the admin to inspect."""
        documents = self.ctx.documents
        left, right = pair.split(":")
        left_text, left_images = pack(documents[left])
        right_text, right_images = pack(documents[right])
        for item in right_text:
            if "image_number" in item:
                item["image_number"] += len(left_images)
        prompt = load_prompt("legacy/comparison") + "\n" + json.dumps(
            {"left": left_text, "right": right_text}, ensure_ascii=False)
        images = left_images + right_images
        if len(images) > MAX_IMAGES or len(prompt) > MAX_PROMPT:
            return pair, {"classification": "uncertain", "confidence": "low", "evidence": [], "differences": [],
                          "limitations": ["Too large for one comparison; admin must inspect both complete originals"]}
        return pair, self.ctx.ask(prompt, COMPARISON, images)

    def apply(self, result):
        """Save one whole-document verdict for later admin review."""
        pair, value = result
        self.ctx.state["pairs"][pair] = value
        self.ctx.checkpoint()
        left, right = pair.split(":")
        print(f"Compared {left[:10]} / {right[:10]}", flush=True)
