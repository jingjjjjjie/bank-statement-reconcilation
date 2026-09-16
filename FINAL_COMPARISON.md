# Final comparison branch — agreed context

Saved 2026-09-16. Planning only: implement this branch once both the bank-statement extraction branch and supporting-document processor are ready. Do not implement it as part of saving this specification. Existing code is not proof that these requirements are complete.

## Purpose and inputs

Reconcile bank transactions against supporting evidence, preserving links to the actual sources. Input one is the verbose bank master CSV, with transaction IDs, amounts, dates, parties, narration and source locations. Input two is the supporting-document processor's results, with stable document IDs, source paths/hashes, extracted content and duplicate decisions.

Actual bank statement and receipt/document content is the evidence. Filenames and folder names must not establish amounts, dates, parties or a match. Extraction can be wrong; source previews must remain available for review. The unrelated sample workbook supplies style only.

## Confirmed decisions

- Review every proposed match initially. No automatic approval, including apparently exact matches. The reviewer can approve, reject or correct a proposal.
- Flag every amount difference, showing both source amounts and the difference. Never silently tolerate, round away or invent a reason for a discrepancy.
- Final report statuses are **Supporting** and **No supporting**. Supporting requires reviewer-approved evidence. Missing or unresolved evidence remains No supporting, with a separate reason/review state so pending review is distinguishable from a missing document. Update the status when evidence is subsequently confirmed.
- Missing or conflicting support does not block export; export with clear flags and notes. Approval must not hide an unresolved amount difference.
- Skip accounting categories and classification rules for now. Do not infer travel/supplies/etc. or fill classification columns automatically.
- Keep bank-only PARTICULAR blank. At final comparison, particulars may be populated from approved supporting evidence; accounting categories remain out of scope.
- Default model is GPT-5.6 Sol through `codex exec` and the existing ChatGPT login. Python handles deterministic extraction, candidate checks, arithmetic, allocations and state. Follow AGENTS.md for structured responses, unresolved failures and per-attempt usage tracking. Sol is not guaranteed error-free.

## Two final pages

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
