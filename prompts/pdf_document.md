Read the entire supplied PDF in this single extraction request. All supplied source units belong to the same original file; they may be pages or text parts of pages. There is no separate assembly call after this request.

Inspect every source unit and attached image. Return reviewed_units containing every supplied source_unit exactly once, including blank or unrelated pages. For every payable piece, return source_units identifying all supporting units and source_locations identifying the actual printed pages or regions. Use source_unit numbers for coverage; use location labels for human-readable page references.

Establish receipt and invoice boundaries across all pages while extracting. Continuation pages and repeated totals belong to the same obligation, not extra expenses. Separate receipts and separately payable recipients remain separate pieces. For uncertain boundaries retain provisional pieces; never force a merge. The user checks the pieces against the original before accepting. Never infer an unprinted total by adding page amounts.

Retain document summary, explicit labelled totals and readability. Unknown factual fields stay empty. Do not return document_type or limitations. Return only the required structured JSON, without approvals.
