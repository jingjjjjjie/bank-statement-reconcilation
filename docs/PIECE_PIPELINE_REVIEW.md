# Piece pipeline cleanup and detailed review

Reviewed 2026-09-19. Scope: extraction, document assembly, human piece editing,
search, matching context, allocation decisions, and final CSV/report output.

## Agreed boundaries

- Two separate receipts are two pieces, including receipts from the same payee.
- Two payees in a claim/payroll schedule are separate payable pieces.
- Multiple purchased items, taxes and subtotals on one receipt are one piece.
- Continuation pages and repeated copies do not create extra payable capacity.
- Search finds pieces; model matching receives complete shortlisted documents and
  their pieces; proposals and human allocations identify specific piece IDs.
- Document totals remain context, not additional allocatable pieces.

## Changes and consumers

| Area | Implementation | Downstream use |
| --- | --- | --- |
| Model output | `prompts/extraction.schema.json`: readable, summary, labelled totals, pieces | Extraction and experimental PDF routing |
| Piece facts | Type, payee, description, typed references/dates, amount, currency, amount basis, source locations | Editor, search, candidate retrieval, matching |
| Assembly | `receipt_assembly.schema.json` adds complete unit coverage | Joins continuation pages without multiplying totals |
| Identity | Python assigns persistent IDs; edits/reordering retain IDs; split/merge creates fresh IDs and parent lineage | Search and ledger allocations |
| Editor | Payee/description/amount/currency rows; secondary details; add/split/merge/remove | Explicit human corrections and acceptance |
| Matching | Current reviewed pieces replace frozen benchmark facts after migration | Candidate search, full-document proposals, human final review |
| Ledger | `final-review/decisions.json` remains the only active final allocation ledger | Remaining capacity, stale flags, history, CSV and final report |
| Usage | Existing Codex reviewer writes per-attempt usage and workspace accounting | Known totals, cache hits and explicitly unknown failed usage |

The model no longer generates parallel `money`, narrative amounts, company/party
lists, receipt classification, and detailed duplicate prose for new extraction.
The old schema and Python projections remain deliberately as compatibility
boundaries for historical records, duplicate-review tooling and inventory exports.
They do not represent additional model-generated facts. The unused legacy bank
matching editor was removed from the shared frontend receipt controller.
Deterministic candidate retrieval now lives in `reconciliation/candidates.py`;
the live pipeline no longer imports its business rules from a benchmark script.

## Detailed review findings and fixes

1. **Identity was position-based.** Persistent piece IDs now survive edits and
   reordering. Duplicate or foreign submitted IDs are rejected. Stored split
   lineage remains valid after reloading; new lineage must name existing parents.
2. **Matching ignored current review edits.** Live matching reads current accepted
   edits and current source hashes. Old proposals cannot masquerade as proposals
   against new evidence: their binding must match current bank and piece facts.
3. **Whole-document context could be omitted.** Each shortlisted parent supplies
   every prepared unit and image once per request, plus all its pieces and labelled
   totals. The model may select another supplied piece from that document. Oversized
   input is explicitly unresolved; source text/images are never silently truncated.
4. **Old allocations could be reused after a split.** Saved allocations retain
   their evidence revision and an item snapshot. Removed pieces remain as stale
   historical items, with their allocation reserved. Other transactions cannot
   allocate revised pieces from that document until stale reservations are undone.
5. **Historical approvals could be silently promoted.** Migration backs up the old
   ledger and keeps decisions/history. Frozen allocations stay visibly stale and
   cannot export Supporting until reviewed against current evidence.
6. **An existing bank branch was stored under another run.** Migration retains a
   verified bank import bound to the current manifest, with original paths/hashes.
   Changed original statements invalidate support and block approval/model runs.
7. **Piece search returned document-only labels.** Extraction search includes
   payee, description, references, dates and amount. Matching search uses those
   piece facts, and unmatched results display the piece description and source.
8. **Merge could lose secondary facts.** Merge preserves source locations,
   references, dates and limitations. It leaves the amount blank for explicit
   correction rather than adding potentially duplicate totals.
9. **The extra editor action caused mobile overflow.** The piece toolbar wraps;
   compact piece rows and disclosures remain responsive.
10. **Background work could hide failure.** Setup/model errors are exposed;
    completed responses are checkpointed. The worker pool refills free slots
    immediately and Stop cancels subscription processes. No model response approves
    a match, even when confidence is strong.

## Deliberate compatibility and limits

- Old extraction records can lack payee/date/reference metadata. No values are
  guessed during migration; edit or regenerate the affected document to fill them.
- Existing legacy *receipt-match* approvals must be undone before activating the
  final ledger. The migration rejects that condition rather than reserving the
  same evidence in two ledgers. Historical frozen final-review decisions are
  preserved by the supported migration.
- Search can miss an ambiguous reimbursement with no matching name/reference or
  amount. Manual search across pieces remains available. A shortlist is not proof
  that no supporting evidence exists.
- Multiple documents can describe the same expense. The model is instructed to
  flag that relationship; human review must check it. Piece IDs alone cannot prove
  two independently extracted receipts represent distinct economic obligations.
- Model interpretation is not guaranteed by software tests. Verification here
  uses deterministic fixtures and browser interactions, not a new customer-corpus
  model run or concurrency benchmark.

## Verification

Unit coverage includes legacy reading, canonical model output through extraction,
strict schemas, source integrity, stable IDs, split lineage, edits/removal after
approval, over-allocation, stale reservations, bank import, CSV support flags,
whole-document payloads, and refilling a free worker while another request stalls.

Playwright covers compact editing, add/split/merge, saved typed-reference search,
reload, live-ledger activation, unmatched-piece search, review actions, final report,
and narrow-screen layout. Test counts and live deployment verification are recorded
in the task completion message.
