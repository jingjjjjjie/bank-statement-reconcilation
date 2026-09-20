# PDF reading modes

Settings → PDF processing offers Vision, Text + checked vision fallback, and
Compare text and vision. The two experimental modes require development mode
and pictures. Vision is the default for new configurations. Existing saved
settings are preserved, including legacy text-only and sparse-page modes.
Save the chosen mode and prepare/refresh the review before running it. Changing
the mode invalidates prepared content; the normal refresh archives earlier
results and decisions. Switching development off blocks experimental runs until
Vision is selected and the review is prepared again.

## Routing

Preparation stores full-page images and native word positions. Bitmap content
(even a logo), missing/garbled text, hidden or translucent text, rotated or
overlapping text, very long pages and complex vector graphics bypass the text
attempt. This deliberately prefers false alarms over silently omitted receipts.

Hybrid additionally requires a layout fingerprint in the local JSON array
`config/pdf-layouts.local.json`. The allowlist starts empty; no layout is
automatically approved by model output or benchmark agreement. Add an audit's
`layout` value only after checking representative originals against accepted
receipt fields. Geometry fingerprints are deliberately strict and may fail to
recognize similar invoices with different values or wrapping.

The text result must be readable, unambiguous, and contain one receipt with
printed total and currency. Critical values must have exact native word
evidence. Legacy uncertainty notes, system review warnings, missing evidence, conflicting extracted totals, malformed
responses and failed calls trigger full-page vision. Budget exhaustion and
cancellation stop processing; they never trigger extra fallback calls.

Ten percent of passing hybrid inputs, selected deterministically by text hash,
also receive vision. Compare mode always retains the vision result; it attempts
text only on structurally eligible pages, without requiring an approved layout.
Differences in receipt count, totals, currencies or invoice numbers are marked
for human review. No route automatically accepts a receipt. Receipt assembly retains its existing visual evidence. Normal dashboard/CLI runs end after extraction and assembly; historical duplicate-comparison helpers are not part of that flow.

These checks cannot prove completeness or accuracy. Arithmetic is not inferred
from an incomplete list of line items; there is no general arithmetic guarantee.
Scanned pages go directly to vision, not a new OCR service. Local extraction
does not make model calls, but text inference and visual fallback both do.

## Audit and benchmark

Per-unit audits live in `review/pdf-routing/`: route, reasons, layout signature,
both results, evidence locations, disagreement and finished/unresolved status.
The existing durable token log records `pdf_text` and `pdf_vision` separately,
including failures, unknown usage and zero-new-token cache hits. Original files
are never changed. Request caches remain keyed by model, instructions, schema
and actual image bytes.

Run the bounded benchmark inside the existing application environment:

```sh
PYTHONPATH=. python scripts/benchmark_pdf_routes.py \
  --index duplicated/projects/PROJECT/review/index.json \
  --output duplicated/benchmarks/pdf-routes-NEW --pages 10
```

The output directory must be new. It scans local page structure, samples up to
eight distinct eligible documents and two risky pages, and uses the existing
ChatGPT subscription through `codex exec` (GPT-5.6 Sol). Shared response-cache
reuse is disabled for measurement; provider prompt caching remains possible.
The report covers page extraction only, not total workflow savings. Compare
matched eligible pages separately from fallback pages. Model agreement is not
human-verified accuracy. Token totals with unknown attempts are partial.
