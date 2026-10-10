# Extraction prompt files

Python joins `core.md` + `document_kinds.md` into every extraction request (single page, image or sheet;
whole PDF; and multi-unit assembly). `../shared/styles.md` is prepended to every model request.

| File | Purpose |
| --- | --- |
| `core.md` | Fixed rules and field meanings. |
| `document_kinds.md` | Customer-editable kinds; each `## Heading` is an allowed piece type. Add a line when you see a mistake. |
| `extraction.schema.json` | Model output for one page, image or sheet. `piece_type` is restricted to the kinds headings at load time. |
| `pdf_document.md` | Added for PDFs read in one request: page coverage. |
| `receipt_assembly.md` + `receipt_assembly.schema.json` | Added when per-unit results are combined across a longer document. |
| `pdf_text.md` | Experimental text-only PDF route. |
| `extraction.legacy.schema.json` | Validates stored records, including older extractions; not sent to the model. |
| `samples/` | A synthetic payout sheet: the exact prompt sent and the model's real output. |

Pieces carry type, payer, payee, other names, short description, amount, amount location, currency, date, document number and
references; documents carry readable, description (at most 20 characters) and labelled totals. After each
response Python rounds amounts to positive cents, turns a month into its last day, maps RM to MYR, fills an
empty currency with MYR (flagged as the default) and skips zero amounts with a review warning.

Edits apply to new requests without a restart and change the cache key. Existing results change only through
Regenerate document or `prepare --refresh`, both of which need fresh acceptance. Keep field names compatible
with the schemas; renaming fields also needs Python and UI changes.
