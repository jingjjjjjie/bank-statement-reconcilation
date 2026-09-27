# Live matching retrieval policy

Updated 27 September 2026. Generate matches ranks candidates in Python
(`reconciliation/matching/ranking.py`) and asks the model only about batches of bank lines
(`dashboard/services/piece_match_jobs.py`). The instructions are `prompts/matching/matching.md`.

## Candidates for one bank line

Every candidate must match the amount, the name, or a filename. Nothing else qualifies.

1. **Amount matches first.** Pieces within RM 0.05 of the bank amount (sen rounding; the
   difference stays visible), then documents with two or more pieces whose printed total
   (each printed total is tried) or, without one, the sum of pieces matches. A document
   total offers all its pieces. Within the amount group, name similarity orders the list,
   then date closeness. An exact reference or document number in the bank note also qualifies.
2. **Then name matches.** Pieces whose payee, payer or other names reach 0.35 trigram
   similarity with the bank name, whatever their amount. Similarity is IDF-weighted over
   three-letter chunks, which tolerates truncated bank names, spacing and honorifics.
   Agency acronyms are expanded (KWSP/EPF, PERKESO/SOCSO/EIS, LHDN/PCB, HRDF, TNB).
3. Up to **30** content candidates are kept. Currency conflicts are excluded; unknown
   currencies stay eligible.
4. **Up to 10 filename candidates** are added: pieces of documents whose folder or file
   name shows the bank amount (dates and single digits ignored). They are labelled
   "found by filename" and never make a match strong on their own.
5. A line with no candidate is recorded as none found without a model call.

## Model requests

Lines that share candidates are packed into the same request so the model can use each
piece once; requests hold up to 20 lines and are halved until the text fits 180,000
characters. The payload carries extracted facts and native document text, without page
images. Proposals are validated against each line's own candidates; combined allocations
beyond a piece's amount, and filename-only strong proposals, become tentative. Each run
saves `final-review/piece-matching/retrieval.json` with every candidate's route and reason.

All proposals need human approval in Final review. Tests use local fixtures only; no live
accuracy claim follows from them. The previous 20-name/20-amount retrieval
(`reconciliation/matching/retrieval.py`) remains for historical benchmarks.
