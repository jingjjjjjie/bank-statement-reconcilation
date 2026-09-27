"""Pluggable model stages for one workflow run: page extraction and receipt assembly.

A stage is any object with:
- `jobs()`: yield zero-argument callables, each making one model call;
- `apply(result)`: save one finished job's result and checkpoint;
- `refill`: None, or a callable yielding more jobs once `jobs()` runs dry.

`extraction.workflow.run` runs its stages in order on the shared job runner, so a
stage can be replaced or added without touching the others.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from reconciliation.core.prompts import extraction_prompt, load_prompt
from reconciliation.core.settings import document_stage
from reconciliation.extraction import pdf_routing
from reconciliation.extraction.assembly import ASSEMBLY, current_assembly, input_revision, validate_assembly
from reconciliation.extraction.pdf_groups import chunk_requests, save_chunk, save_result, whole_request
from reconciliation.extraction.reader import extract
from reconciliation.extraction.schemas import EXTRACTION
from reconciliation.model.client import MAX_IMAGES, MAX_PROMPT


class ReviewPending(ValueError):
    """A required earlier workflow step is not complete."""


@dataclass
class RunContext:
    """Everything a stage needs from the current run; stages share no other state."""
    work: Path
    config: dict
    state: dict
    documents: dict
    selected: dict
    regeneration: dict
    ask: Callable
    checkpoint: Callable
    progress: Callable | None = None
    dispatched: set = field(default_factory=set)
    whole_completed: set = field(default_factory=set)

    def with_regeneration(self, digest, prompt):
        """Append an explicit regeneration request so it bypasses earlier cached answers."""
        return prompt + "\nRegeneration request: " + self.regeneration[digest] if digest in self.regeneration else prompt

    def report(self, digest, status):
        """Forward per-document progress to the dashboard, if it is listening."""
        if self.progress:
            self.progress(digest, status)


def pack(document):
    """Return every unit's text and images; never silently truncate an original."""
    text, images = [], []
    for unit in document["units"]:
        text.append({"document_id": document["id"], "location": unit["label"], "text": unit["text"],
                     "limitation": unit.get("limitation", "")})
        if unit["image"]:
            images.append(unit["image"])
            text[-1]["image_number"] = len(images)
    return text, images


def is_pending(document):
    """Only accepted, readable documents take part in model stages."""
    return document.get("accepted", True) and not document["error"]


class UnitExtraction:
    """Read each document: whole short PDFs, grouped long PDFs, or unit by unit."""

    def __init__(self, ctx, queued_regenerations=None):
        """Optionally pick up regenerations queued while this stage is running."""
        self.ctx = ctx
        self.queued = queued_regenerations
        self.refill = self._refill if queued_regenerations else None

    def jobs(self):
        """Yield unread units lazily so a large corpus is never queued at once."""
        ctx = self.ctx
        for digest, document in ctx.selected.items():
            if digest in ctx.dispatched or not is_pending(document):
                continue
            regenerate = digest in ctx.regeneration
            whole = whole_request(document, ctx.config, ctx.state, regenerate)
            if whole is not None:
                ctx.dispatched.add(digest)
                yield self._whole_job(digest, document, *whole)
                continue
            for numbers, prompt, images in chunk_requests(document, ctx.config, ctx.state, regenerate):
                keys = {f"{digest}:{n - 1}" for n in numbers}
                if not keys & ctx.dispatched:
                    ctx.dispatched.update(keys)
                    yield self._chunk_job(digest, numbers, prompt, images)
            for number, unit in enumerate(document["units"]):
                key = f"{digest}:{number}"
                if unit.get("blocked") or key in ctx.dispatched or (key in ctx.state["units"] and not regenerate):
                    continue
                ctx.dispatched.add(key)
                yield self._unit_job(digest, document, unit, key)

    def _whole_job(self, digest, document, prompt, images):
        """Read all PDF pages and establish piece boundaries in one model call."""
        def job():
            self.ctx.report(digest, "running")
            value = self.ctx.ask(self.ctx.with_regeneration(digest, prompt), ASSEMBLY, images, stage="pdf_document",
                                 verify=lambda result: validate_assembly(result, len(document["units"])))
            return None, digest, "whole PDF", value
        return job

    def _chunk_job(self, digest, numbers, prompt, images):
        """Extract one page group while keeping original document-wide unit numbers."""
        def job():
            self.ctx.report(digest, "running")
            value = self.ctx.ask(self.ctx.with_regeneration(digest, prompt), ASSEMBLY, images, stage="pdf_chunk",
                                 verify=lambda result: validate_assembly(result, len(numbers), source_units=numbers))
            return numbers, digest, f"PDF units {numbers[0]}-{numbers[-1]}", value
        return job

    def _unit_job(self, digest, document, unit, key):
        """Read one page, sheet, or image with its file-type model."""
        ctx = self.ctx

        def ask(prompt, schema, images=(), **kwargs):
            """Route every call for this unit through the regeneration-aware ask."""
            return ctx.ask(ctx.with_regeneration(digest, prompt), schema, images, **kwargs)

        def job():
            ctx.report(digest, "running")
            stage = document_stage(document["paths"][0])
            if stage == "pdf" and ctx.config["pdf_mode"] in pdf_routing.MODES:
                value = pdf_routing.extract_unit(unit, ask, ctx.config["pdf_mode"],
                                                 ctx.work / "pdf-routing" / (key.replace(":", "-") + ".json"))
                return key, digest, unit["label"], value
            prompt = extraction_prompt() + "\n" + json.dumps({
                "location": unit["label"], "text": unit["text"], "limitation": unit.get("limitation", "")},
                ensure_ascii=False)
            return key, digest, unit["label"], ask(prompt, EXTRACTION, [unit["image"]] if unit["image"] else [],
                                                   stage=stage)
        return job

    def apply(self, result):
        """Save one finished extraction before more work is launched."""
        ctx = self.ctx
        key, digest, label, value = result
        document = ctx.documents[digest]
        if key is None:
            save_result(document, ctx.state, value)
            ctx.whole_completed.add(digest)
        elif isinstance(key, tuple):
            save_chunk(document, ctx.state, value, key)
        else:
            ctx.state["units"][key] = value
        ctx.checkpoint()
        if key is None or len(document["units"]) == 1:
            ctx.report(digest, "completed")
        print(f"Read {digest[:10]} / {label}", flush=True)

    def _refill(self):
        """Add newly queued regenerations while workers are still busy."""
        ctx = self.ctx
        for digest, request_id in self.queued().items():
            if digest not in ctx.regeneration:
                ctx.regeneration[digest] = request_id
                ctx.selected[digest] = ctx.documents[digest]
        return self.jobs()


class ReceiptAssembly:
    """Join multi-unit documents into receipts without repeating page extraction."""

    refill = None

    def __init__(self, ctx):
        """Bind the stage to one run."""
        self.ctx = ctx

    def jobs(self):
        """Yield one assembly per complete, not-yet-assembled multi-unit document."""
        ctx = self.ctx
        for digest, document in ctx.selected.items():
            if (digest in ctx.whole_completed or not is_pending(document) or len(document["units"]) < 2
                    or (digest not in ctx.regeneration and current_assembly(document, ctx.state))):
                continue
            if any(unit.get("blocked") or f"{digest}:{n}" not in ctx.state["units"]
                   for n, unit in enumerate(document["units"])):
                continue
            yield lambda digest=digest, document=document: self._assemble(digest, document)

    def _evidence(self, digest, document):
        """Use vision renders of PDF pages when pictures are on, else the prepared units."""
        config = self.ctx.config
        path = Path(document["paths"][0])
        if path.suffix.lower() == ".pdf" and config["pictures_enabled"] and config["pdf_mode"] not in pdf_routing.MODES:
            units = extract(path, self.ctx.work / "assets" / "receipt-assembly" / digest, {**config, "pdf_mode": "vision"})
            return {**document, "units": units}
        return document

    def _assemble(self, digest, document):
        """Inspect all source units before proposing document receipt boundaries."""
        ctx = self.ctx
        originals, images = pack(self._evidence(digest, document))
        payload = [{"source_unit": n + 1, "original": original, "extraction": ctx.state["units"][f"{digest}:{n}"]}
                   for n, original in enumerate(originals)]
        prompt = ctx.with_regeneration(digest, extraction_prompt() + "\n\n" + load_prompt("extraction/receipt_assembly")
                                       + "\n" + json.dumps(payload, ensure_ascii=False))
        if len(images) > MAX_IMAGES or len(prompt) > MAX_PROMPT:
            raise ReviewPending("Document too large for receipt assembly; boundaries remain unresolved")
        value = ctx.ask(prompt, ASSEMBLY, images, stage=document_stage(document["paths"][0]),
                        verify=lambda result: validate_assembly(result, len(document["units"])))
        return digest, {**value, "input_revision": input_revision(document, ctx.state)}

    def apply(self, result):
        """Save each assembled document independently for safe resume."""
        digest, value = result
        self.ctx.state.setdefault("assemblies", {})[digest] = value
        self.ctx.checkpoint()
        self.ctx.report(digest, "completed")
        print(f"Assembled receipts {digest[:10]}", flush=True)
