# Editable styles and prompts

Edit these UTF-8 Markdown files to change the instructions sent to Codex:

| File | Purpose |
| --- | --- |
| `styles.md` | Shared review style and rules prepended to every request. |
| `extraction.md` | Extract one page, sheet, or image. |
| `screening.md` | Screen document summaries for possible matches. |
| `comparison.md` | Compare complete original documents. |
| `connection_test.md` | Read the synthetic receipt in the live connection test. |

Python reads these files when building each new request; no server restart is
needed. Document data is appended as JSON, and images are attached separately.
These files contain instructions only: no placeholders or Python expressions
are required. Missing or empty files fail the request rather than falling back
to hidden instructions. Keep requested output fields compatible with the JSON
schemas in `reconciliation/codex_reviewer.py`.

Stop an active review before editing. To apply edits to already completed units
or comparisons, run the existing `prepare --refresh` workflow before reviewing
again. Refresh archives prior state and decisions. Resume alone retains completed
work. Changed request text gets a different cache key; unchanged requests can
still reuse cached responses. Each executed request's full prompt remains saved
in its `model-cache/<hash>/prompt.txt` for auditing.

`styles.md` controls model instructions. `styles/bank_statement.xml` controls
Excel formatting deterministically; it is never sent to the model. See
[workbook style instructions](styles/README.md) for editing it.
