# Editable prompts

Edit these UTF-8 files to change what is sent to Codex. Python reads them for each new
request, so no restart is needed. Document data is appended as JSON and images are attached
separately. Missing or empty files fail the request instead of falling back to hidden text.

| Folder | Files | Used for |
| --- | --- | --- |
| `shared/` | `styles.md`, `connection_test.md` | Rules prepended to every request; the live connection test. |
| `extraction/` | `core.md`, `document_kinds.md`, schemas, `pdf_document.md`, `receipt_assembly.md`, `samples/` | Reading documents into pieces. See [extraction/README.md](extraction/README.md). |
| `matching/` | `matching.md` | Generate matches in Final review: pieces vs documents, candidates, decisions. See `docs/workflow/MATCHING_RETRIEVAL.md`. |
| `legacy/` | `extraction.md`, `matching_policy.md`, `piece_matching.md` | Previous prompts, kept for historical benchmarks; not used by normal runs. |
| `excel/` | `bank_statement.xml` | Bank-only Excel formatting; never sent to the model. See [excel/README.md](excel/README.md). |

Keep output fields compatible with the schemas in `extraction/`. Changed text gets a new cache
key; unchanged requests reuse cached responses. Each request's full prompt is saved in its
`model-cache/<hash>/prompt.txt`.

Stop an active review before editing. To apply edits to completed documents, run
`python -m reconciliation.extraction.workflow prepare --refresh`; refreshed results require fresh acceptance.
