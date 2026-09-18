# Editable styles and prompts

Edit these UTF-8 Markdown files to change the instructions sent to Codex:

| File | Purpose |
| --- | --- |
| `styles.md` | Shared review style and rules prepended to every request. |
| `extraction.md` | Extract one page, sheet, or image. |
| `pdf_text.md` | Extract eligible PDF text with native word evidence in experimental routing. |
| `receipt_assembly.md` | Assemble receipt boundaries across a document's extracted units and original pages. |
| `screening.md` | Historical duplicate-summary screening; not used by normal extraction-only runs. |
| `comparison.md` | Historical duplicate comparison of complete originals; not final bank pairing. |
| `connection_test.md` | Read the synthetic receipt in the live connection test. |

Python reads these files when building each new request; no server restart is
needed. Document data is appended as JSON, and images are attached separately.
These files contain instructions only: no placeholders or Python expressions
are required. Missing or empty files fail the request rather than falling back
to hidden instructions. Keep requested output fields compatible with the JSON
schemas in `reconciliation/codex_reviewer.py`, `reconciliation/receipt_assembly.py` and `reconciliation/pdf_routing.py`.

Normal dashboard and CLI runs use extraction and assembly; retained duplicate prompts do not imply a second vision duplicate pass. Final pairing experiment prompts live in `scripts/test_statement_matching.py`; the current final-review/report pages read saved proposals and make no model calls.

Stop an active review before editing. To apply edits to already completed units
or comparisons, run the existing `prepare --refresh` workflow before reviewing
again. Refresh archives prior state and decisions. Resume alone retains completed
work. The dashboard's Regenerate document action can request fresh extraction/assembly for one document and requires fresh acceptance. Changed request text gets a different cache key; unchanged requests can
still reuse cached responses. Each executed request's full prompt remains saved
in its `model-cache/<hash>/prompt.txt` for auditing.

`styles.md` controls model instructions. `styles/bank_statement.xml` controls
Excel formatting deterministically; it is never sent to the model. See
[workbook style instructions](styles/README.md) for editing it.
