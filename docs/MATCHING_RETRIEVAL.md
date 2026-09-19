# Live matching retrieval policy

The live Generate matches action uses `reconciliation/matching_retrieval.py`.
Historical benchmark scoring remains available separately for comparisons.

1. Reserve exact, typed or labelled invoice/receipt/payment/booking/order/claim IDs.
   Case and whitespace are normalized; punctuation and leading zeros are retained.
   Identifier boundaries prevent prefix matches. Tax/account IDs and merchant words
   are not promoted to transaction references. Reference-linked currency/direction
   conflicts remain visible and flagged; ordinary conflicting candidates are excluded.
2. Independently select up to 20 name matches and 20 exact-amount matches.
   Existing full-name and anchored truncated-name checks remain retrieval aids.
   Within each route: exact reference, BM25 description relevance, date proximity,
   then stable ID for deterministic ties. Dates never impose an exclusion window.
3. Merge/deduplicate with reference reservations and cap at 40 IDs. Reference
   reservations displace the lowest-ranked ordinary candidates when necessary.
4. If fewer than 10 IDs remain, top up to 10 using positive BM25 matches only.
   Boilerplate and bank-recipient name words are removed from the description query.
   Missing amounts are not equal amounts; missing/unparsed dates sort after known dates.

Each run saves `final-review/piece-matching/retrieval.json` with route counts,
selected IDs, reasons, omitted counts and reference overflow. These are search
diagnostics, not confidence scores. More than 40 exact references is explicitly
incomplete. A model no-match result from an incomplete shortlist becomes tentative
with a visible omitted-count explanation.

Full original parent documents and all their pieces remain available as context.
Only the selected (at most 40) `candidate_ids` may receive allocations in a live
run. A contextual piece outside this list must trigger further retrieval/review,
not an invented allocation. Compact piece records retain substantive facts while
omitting redundant metadata; source images/text are not truncated. Existing size
limits still leave oversized requests unresolved. Token costs therefore include
full source context, not merely the compact JSON estimates.

The editable shared instructions are `prompts/matching_policy.md`; the full-document
piece contract remains in `prompts/piece_matching.md`. Related bank context includes
other payments whose selected evidence intersects these parent documents. Final
human allocation checks still enforce remaining balances globally.

Changing retrieval does not rescore or approve existing saved matches. Generate
matches explicitly to produce new proposals. Tests use local fixtures and the saved
Canva example; no live model accuracy claim follows from these deterministic tests.
