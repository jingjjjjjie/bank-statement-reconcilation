// Instructions live here so each page can keep its controls and results concise.
export const pageHelp = {
  Source: ['Choose your workspace', [
    'Choose a folder containing statement/ with one bank-statement PDF and documents/ with supporting files.',
    'Resume workspace returns to your last page without restarting the review.',
    'Use Browse folders or enter the folder path, then select Proceed. Exact duplicates are copied to output/duplicates/; originals stay in place.',
  ]],
  Bank: ['Bank Statement Extraction', [
    'Load for final matching prepares the current bank statement and extracted supporting pieces. Generate matches starts matching here; Stop pauses it. The progress bar shows processed transactions and failures. Review the results on Review Matching. Loading alone does not start model calls.',
    'Enter the year printed on the statement, then extract it. Check the transactions and balances against the original PDF.',
    'Use Check bank extraction when ready. Search filters the statement rows.',
  ]],
  Documents: ['Documents', [
    'Run all documents to extract the remaining files. Progress is saved; Stop pauses new requests while active calls finish.',
    'Search or filter the list, then open Review Extraction to check each extraction against its original.',
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
    'Two receipts or two payees are separate pieces; purchase lines on one receipt are one piece. Use Add entry for a missed receipt. Merge all combines the current entries, sums complete amounts in one currency and keeps source references; check the merged total before accepting. Reset to original restores the latest model extraction before your edits or merges; Accept saves the reset. The highlighted entry is selected; Remove deletes it from the extraction. The icon beside the filename shows review status. Accept & next saves your review and opens the next document. Discard & next also advances after saving. Failed saves stay on the current document. Accept and Discard switch directly between statuses; Undo is optional. Undo accept reopens it and keeps corrections. After editing an accepted document, use Accept again. Accepted documents show Undo accept; discarded documents show Undo discard. Undo stays on the current document. On the last document, Accept and Discard save without advancing. Unavailable actions stay visible in grey. Next opens the following document separately. Accept all saves all ready results, including current edits; trash and unresolved results are skipped. Bank matches still require separate review.',
    'Discard classifies the whole document as trash and excludes it from supporting evidence. The original stays intact. Reopen its numbered square and use Undo discard to undo.',
    'Details holds type, other names, references and Amount at; Show jumps the original to that page or sheet rows. "Currency (default)" means no currency was found and MYR was assumed.',
    'Options contains Reload results, Export reviews and Accept all. Reload results fetches the latest saved results.',
    'Export reviews downloads saved reviews as benchmark ground truth: accepted pieces, discarded documents, and pending documents without pieces. Unsaved edits are not included.',
  ]],
  Matching: ['Review Matching', [
    'Open Edit allocation on a selected document to choose Counts toward amount or Supporting only. Supporting only contributes no money. Role and allocation edits are drafts until Confirm / Save; changing a role updates the total and difference immediately.',
    'Load for final matching on the Bank statement page prepares the current bank and extracted pieces. Generate matches, Stop and matching progress are also on the Bank statement page. Matching proposals still require your review.',
    'Review one bank transaction at a time. Use the transaction selector, filters or Next to move to another payment.',
    'Scroll through supporting candidates on the left. Expand a card for its details and original preview on the right. Inspecting a candidate does not select or approve it.',
    'Show opens the original evidence. Use checkboxes to add candidates and Remove to deselect them. Confirm supporting saves your decision; incomplete coverage remains No supporting.',
    'Search all pieces broadens the shortlist. Check original parties, amounts and receipt boundaries; equal amounts alone do not establish a match. Warnings and differences must be reviewed.',
    'Reject suggestion rejects the saved proposal; other evidence may exist. Undo decision releases its allocations. Unmatched pieces uses the same review ledger.',
  ]],
  FinalReport: ['Export', [
    'Search or filter the transaction report. View evidence opens confirmed supporting documents.',
    'Download the bank statement workbook or document ZIPs here. Unmatched documents exclude duplicates and documents with a confirmed match. Original project contains input files, not application or review state.',
    'Export Excel uses the bank statement workbook format, with or without supporting evidence paths. Confirmed, fully supported matches show OK; other remarks stay blank.',
    'Return to Review Matching to change decisions. The report reflects the current saved ledger.',
    'Workflow and recorded token usage are available inside Export. Unknown usage makes totals incomplete.',
  ]],
  Settings: ['Review settings', [
    'Set document processing, models, reasoning effort and request limits, then Save settings. Saving does not start processing.',
    'Codex account: green means working, blue busy, red a problem. Login is rechecked every minute. Check now sends one tiny real request, recorded in token usage. Check for updates asks for the latest Codex; Update installs it for new requests on this computer only. To rebuild the image with it, run python scripts/codex/update_codex.py on the host. Log in with ChatGPT shows a link and a one-time code.',
    'PDF pages per call defaults to 5. Short PDFs use one call; longer PDFs use groups up to that limit, then whole-document assembly. Saved pages are preserved on resume. Testing modes and oversized groups keep the page route.',
    'PDF vision reads every page. Testing modes require development mode and pictures. Changing processing modes requires refreshed inputs; previous results are archived.',
    'Turning pictures off leaves image-dependent documents unresolved. Turning Codex off stops new model requests; active calls may finish.',
    'The request limit is shared by extraction and receipt assembly, including failed attempts. Cache reads use no new requests. Run again to resume saved work with a fresh allowance.',
    'Parallel requests controls simultaneous calls for the next run. More workers may hit subscription limits. Request limits are not token or spending caps.',
    'Token counts come from reported usage. Cached input is part of input tokens; unknown attempts mean totals are incomplete.',
    'Development mode enables shared caching and explicit decision replay for unchanged files. Turning it off preserves saved data.',
  ]],
};
