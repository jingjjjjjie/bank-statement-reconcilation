# Final comparison branch — agreed context

Saved 2026-09-16. The user subsequently authorized implementing the in-app final review using the frozen matching cache (2026-09-18). `/matching` now reviews that snapshot; it does not imply that current extraction/assembly or general multi-session imports are complete. The original broader requirements and remaining open decisions follow.

Current implementation: all 240 saved bank entries, original evidence previews, candidate selection, approve/deny/undo, shared remaining balances, unmatched-supporting view, history and CSV export. Human decisions live in the active project's `final-review/decisions.json`, bound to the exact cached evidence. No model calls occur during review. A changed cache requires a separate import/migration; it cannot silently inherit approvals. The frozen cache is currently the explicitly authorized `full-statement-240` experiment and must match the active project manifest. Legacy receipt-match approvals must be migrated or undone before starting this ledger; the two workflows cannot reserve the same evidence independently.

Conservative interim export rule for the still-open partial-support question: only a current approval whose monetary allocations fully cover the bank payment receives Supporting. Partial/context-only approvals remain visibly approved but export No supporting with their difference and notes. This policy is exposed in the UI and can be revisited without losing decision history. Missing source amounts/currencies are not guessed; such documents can be attached as contextual evidence. Cross-currency conversion and correction of cached monetary facts are outside this snapshot review.

## Purpose and inputs

Reconcile bank transactions against supporting evidence, preserving links to the actual sources. Input one is the verbose bank master CSV, with transaction IDs, amounts, dates, parties, narration and source locations. Input two is the supporting-document processor's results, with stable document IDs, source paths/hashes, extracted content and duplicate decisions.

Actual bank statement and receipt/document content is the evidence. Filenames and folder names must not establish amounts, dates, parties or a match. Extraction can be wrong; source previews must remain available for review. The unrelated sample workbook supplies style only.

## Confirmed decisions

- Final pairings stay in one transaction list with High / Low confidence and a separate Pending / Approved / Rejected decision. Confidence can be filtered independently; unpaired transactions show No match. High uses the saved strong assessment, downgraded for stale/excluded evidence, unresolved boundaries, incomplete amount coverage, or a changed saved supporting selection. The saved reason is shown; confidence is not a calibrated probability or approval. Draft edits are not automatically rescored.

- Review every proposed match initially. No automatic approval, including apparently exact matches. The reviewer can approve, reject or correct a proposal.
- Flag every amount difference, showing both source amounts and the difference. Never silently tolerate, round away or invent a reason for a discrepancy.
- Final report statuses are **Supporting** and **No supporting**. Supporting requires reviewer-approved evidence. Missing or unresolved evidence remains No supporting, with a separate reason/review state so pending review is distinguishable from a missing document. Update the status when evidence is subsequently confirmed.
- Missing or conflicting support does not block export; export with clear flags and notes. Approval must not hide an unresolved amount difference.
- Skip accounting categories and classification rules for now. Do not infer travel/supplies/etc. or fill classification columns automatically.
- Keep bank-only PARTICULAR blank. At final comparison, particulars may be populated from approved supporting evidence; accounting categories remain out of scope.
- Default model is GPT-5.6 Sol through `codex exec` and the existing ChatGPT login. Python handles deterministic extraction, candidate checks, arithmetic, allocations and state. Follow AGENTS.md for structured responses, unresolved failures and per-attempt usage tracking. Sol is not guaranteed error-free.

## Final report after review

`/final-report` is a read-only view of the same saved ledger, reached from Final review or navigation. It lists every transaction with Supporting / No supporting and the human decision, search and support filters, and CSV export. Pending rows remain visible with an explicit incomplete-review notice. It is a live report, not a locked archival snapshot.

View evidence opens a modal with the original statement at the transaction page alongside approved supporting documents. Document switches show each saved allocation; page and zoom controls, original downloads, totals, differences, flags and notes remain available. Pending or rejected proposals are never shown as approved evidence. Changed sources are flagged and previews retain hash validation. Escape or Close restores focus and preserves filters; mobile uses a full-screen stacked pane and transaction cards. No new model calls or review writes occur.

## Two review views

The agreed review design is currently implemented as Transactions and Unmatched documents tabs within `/matching`. The separate read-only `/final-report` page follows review.

### 1. Statement ready for export / final review

Show every bank transaction, including those without support: date, party, narration, bank amount, support status, matched documents, allocated amounts, differences, review state and notes.

Evidence is clickable and opens an image/PDF preview at the relevant page when available. Show the bank evidence alongside supporting evidence so the reviewer can verify the proposed match. Provide approve/reject/correct actions.

Export CSV listing which transactions have support and which do not, with document IDs/paths or links, amounts, differences and notes. Preview is an application feature; CSV carries evidence references, not embedded interactive previews. Preserve the existing styled statement export where applicable.

### 2. Unmatched supporting documents

Show documents not fully matched, excluding confirmed duplicate copies. Preserve the retained canonical document and original-location provenance. A suspected duplicate is not automatically an approved duplicate.

Provide **Match to transaction**:

1. Preview the document.
2. Search bank transactions by amount, date, party/name or reference.
3. Select one or several transactions and enter allocated amounts.
4. Show discrepancies and existing allocations; the reviewer confirms.
5. Update both pages from the same saved match state. Fully allocated documents leave the unmatched list; partially allocated documents stay with their remaining amount.

Provide **Undo / Change match**, retaining decision history. A document discovered here can be linked after the initial statement review and the corresponding support status must update.

## Matching design to carry forward

- Python proposes candidates using extracted amounts, dates, parties and references. Sol can explain ambiguous relationships; its proposals still require review.
- Support one payment to several documents (grouped reimbursement) and several payments to one document (instalments). The manual allocation flow above was accepted by the user.
- Distinguish multiple evidence documents for one expense from multiple expenses. Invoice + receipt + delivery note must not be added as three payable amounts.
- Track allocations and remaining amounts; prevent accidental reuse or over-allocation. An evidence document can support related payment instalments without counting its total repeatedly.
- Record matches separately from source masters: bank IDs, document IDs, allocated amounts, discrepancy/reason, source evidence, reviewer decision and history. Both pages and exports must derive from that shared state.
- Never force a match just because totals agree. Wrong parties, wrong periods or misread references can survive arithmetic checks.

## Still open — do not assume agreement

- A 30-day candidate-search window was suggested but not explicitly accepted. Decide the default window and expansion behavior; dates should not permanently exclude older valid documents.
- Confirm how a reviewer-approved but partially supported transaction maps to the two final statuses. Preserve pending/partial/discrepancy detail separately regardless.
- Define treatment for non-monetary evidence (maps, labels, QR screenshots), missing totals and document bundles: these cannot all use a simple remaining-amount rule.
- Decide final export column order and particulars format during implementation, following the approved sample style where relevant.

## Implementation acceptance checklist

- Every approval is an explicit reviewer action; model calls never approve matches.
- Source previews open from both pages; filenames are not used as accounting truth.
- Amount differences remain visible in review and export.
- Manual linking, split/group allocations, undo and corrections update both pages consistently.
- Confirmed duplicates are excluded from unmatched documents; partial matches retain residual amounts without double-counting.
- CSV includes all bank transactions, both support statuses and usable evidence references.
- Unresolved records remain reviewable and exportable; no accounting categorization is added.

Read this file when resuming final-comparison work after the two input branches are ready.


## Matching research

See [MATCHING_EXPERIMENTS.md](MATCHING_EXPERIMENTS.md) for measured shortlist and batching experiments. These are design recommendations, not deployed matching behavior or changes to the open decisions above.
