# Editable prompts

Edit these UTF-8 files to change what is sent to Codex. Python reads them for each new
request, so no restart is needed. Document data is appended as JSON and images are attached
separately. Missing or empty files fail the request instead of falling back to hidden text.

| Folder | Files | Used for |
| --- | --- | --- |
| `shared/` | `styles.md`, `connection_test.md` | Rules prepended to every request; the live connection test. |
| `extraction/` | `core.md`, `document_kinds.md`, schemas, `pdf_document.md`, `receipt_assembly.md`, `samples/` | Reading documents into pieces. See [extraction/README.md](extraction/README.md). |
| `matching/` | `matching_policy.md`, `piece_matching.md` | Generate matches in Final review. See `docs/MATCHING_RETRIEVAL.md`. |
| `legacy/` | `screening.md`, `comparison.md`, `extraction.md` | Historical duplicate comparison and the previous extraction prompt; not used by normal runs. |
| `excel/` | `bank_statement.xml` | Bank-only Excel formatting; never sent to the model. See [excel/README.md](excel/README.md). |

Keep output fields compatible with the schemas in `extraction/`. Changed text gets a new cache
key; unchanged requests reuse cached responses. Each request's full prompt is saved in its
`model-cache/<hash>/prompt.txt`.

Stop an active review before editing. To apply edits to completed documents, use Regenerate
document in the dashboard or `prepare --refresh`; both require fresh acceptance.
