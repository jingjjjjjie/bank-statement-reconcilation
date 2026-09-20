# Extraction prompt files

- `styles.md`: shared instructions prepended to model requests.
- `extraction.md`: active page/image/sheet extraction instructions.
- `extraction.schema.json`: editable JSON output schema loaded by Python and
  supplied to Codex through `--output-schema`. It is also used to validate results.
- `pdf_document.md`: whole-document PDF extraction and source coverage, using the assembly-shaped schema in a single extraction call.
- `receipt_assembly.md`: instructions for combining supporting pieces across units.
- `pdf_text.md`: additional instructions for experimental text-only extraction.

The schema is kept alongside the prompt, rather than duplicated inside its text.
Both are part of the model request. Preserve required application field names and
types when editing the schema; changing them may also require Python/UI changes.
Restart long-running application processes after schema edits. New workflow
processes load the schema on startup. Changed schemas produce different request
cache keys. Desktop shortened drafts do not replace the active prompt.

New model output is document context plus pieces. Document-level type and document/piece limitations are omitted; each piece retains its own piece_type. `receipt_assembly.schema.json` adds source-unit coverage and boundary flags. `extraction.legacy.schema.json` is a compatibility validation contract for older records, not the active model output. Python adapters retain old export/routing accessors without asking the model to generate duplicate prose. IDs and approvals are assigned by Python, never the model.
