// Instructions live here so each page can keep its controls and results concise.
export const pageHelp = {
  Source: ['Choose your workspace', [
    'Choose a folder containing statement/ with one bank-statement PDF and documents/ with supporting files.',
    'Resume workspace returns to your last page without restarting the review. Prepare files builds missing previews for an existing workspace.',
    'Use Browse folders or enter the folder path, then select Proceed. Progress shows exact duplicate copying, Excel PDF preview conversion, and local preparation of PDF pages and other files. Originals stay in place; PDF previews are display-only.',
  ]],
  Bank: ['Bank statement', [
    'Enter the year printed on the statement, then extract it. Check the transactions and balances against the original PDF.',
    'Use Check bank extraction when ready. Search filters the statement rows.',
    'Export Excel uses the saved style and company name. Bank fields are filled; PARTICULAR and accounting fields stay blank. Document matches start as PENDING.',
  ]],
  Documents: ['Documents', [
    'Run all documents to extract the remaining files. Progress is saved; Stop pauses new requests while active calls finish.',
    'Search or filter the list, then open Review results to check each extraction against its original.',
  ]],
  ExactReport: ['Exact duplicates', [
    'Inspect each group of identical files. Hashes and full byte comparisons verify duplicates automatically; no selection is needed.',
    'Originals remain in documents/. One copy per hash is processed. Continue to document extraction when ready.',
  ]],
  ExactReview: ['Review duplicates', [
    'Select a group, compare its files, and choose one to retain. Unselected copies are kept in recovery.',
    'Use Undo selection to change a decision. Validate exact review after all groups have a selection.',
    'Development tools can remember decisions and replay them for unchanged files when explicitly applied.',
  ]],
  ExtractionReview: ['Review extraction', [
    'Use the numbered squares to choose a document; green means reviewed. Arrows move between groups of ten. Compare the fields with the original, using page and zoom controls to inspect details.',
    'Search by payee, reference or amount. Two receipts or two payees are separate pieces; purchase lines on one receipt are one piece. Use Split, Merge next, Add piece or Remove to correct boundaries. Accept & next saves your review. Accept all saves all ready results, including current edits; trash and unresolved results are skipped. Bank matches still require separate review.',
    'Not useful — discard classifies the whole document as trash and excludes it from supporting evidence. The original stays intact. Reopen its numbered square and use Restore document to undo.',
    'Excel previews show converted PDF print pages; print areas and hidden sheets may limit what is displayed. Open file shows the complete workbook. These previews do not change extraction or matching.',
    'Reload fetches the latest saved results.',
  ]],
  Matching: ['Final review', [
    'Verify one proposed evidence group against the bank payment. Confirm supporting or reject the suggestion; rejection does not prove no other evidence exists.',
    'Change evidence shows unselected alternatives. Each record shows its party, date and source location; equal amounts alone do not prove a match. Check allocated amounts and differences; add a note where needed. Undo decision allows changes.',
    'Unmatched pieces lists unallocated and partially allocated evidence. Choose a bank transaction to attach it. Contextual documents have no monetary balance.',
    'Use reviewed pieces connects current extraction edits. Generate matches reads the complete shortlisted documents; Stop cancels new work. Historical decisions remain visible and require re-review when their evidence changes.',
    'Pairing confidence is a suggestion, not approval. Only approved evidence fully covering a payment receives Supporting in the report.',
  ]],
  FinalReport: ['Final report', [
    'Search or filter transactions and use View evidence to compare original bank and approved supporting documents.',
    'Export CSV downloads the saved review. Pending, rejected, or incompletely supported payments remain No supporting.',
    'Return to Final review to change decisions. The report reflects the current saved ledger.',
  ]],
  Completion: ['Completion', [
    'Check that each workflow step is complete. Return to the relevant page for any outstanding work.',
    'Token usage is cumulative. Cached input is included in input tokens; attempts with unknown usage make totals incomplete.',
  ]],
  Settings: ['Review settings', [
    'Set document processing, models, reasoning effort and request limits, then Save settings. Saving does not start processing.',
    'PDF vision reads every page. Testing modes require development mode and pictures. Changing processing modes requires refreshed inputs; previous results are archived.',
    'Turning pictures off leaves image-dependent documents unresolved. Turning Codex off stops new model requests; active calls may finish.',
    'The request limit is shared by extraction and receipt assembly, including failed attempts. Cache reads use no new requests. Run again to resume saved work with a fresh allowance.',
    'Parallel requests controls simultaneous calls for the next run. More workers may hit subscription limits. Request limits are not token or spending caps.',
    'Token counts come from reported usage. Cached input is part of input tokens; unknown attempts mean totals are incomplete.',
    'Development mode enables shared caching and explicit decision replay for unchanged files. Turning it off preserves saved data.',
  ]],
};
