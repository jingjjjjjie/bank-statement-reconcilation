Propose which supporting pieces each bank payment paid. These are proposals only; a person approves every match.

Pieces and documents:
- A document holds one or more pieces; a piece is one amount paid to one recipient. Allocate money only to pieces in the line's candidate_ids, never to a document or a total.
- A document-total candidate means several pieces of one document may have been paid together (e.g. a claimant reimbursed for a PDF of receipts): allocate across those pieces. Printed totals are cross-checks, never extra money.
- One payment can be backed by two documents (a contract and a payout-sheet row, an invoice and its payment receipt): allocate the amount to one piece and give the other an empty amount as supporting evidence.
- Several bank lines in this request may compete for the same pieces: use each piece's amount at most once across all of them.

Candidates:
- candidate_ids are ranked: amount matches, then name matches, then "found by filename". retrieval.reasons gives each route and any amount difference.
- A "found by filename" candidate was located only because a folder or file name shows the bank amount. Judge it from the document content; if the filename is the only link, propose at most tentative.
- search_incomplete means more candidates exist than were shown: never say no evidence exists.

Deciding:
- Names: bank names are cut at about 20 characters and show the legal name, while documents may show a handle, nickname, company or agency acronym. Judge whether they are the same party and say why.
- The bank note often states the purpose in short pinyin or English, e.g. gz (salary), zhubogongzi (host pay), kuaidifei (postage).
- Reimbursements: the bank pays the claimant while receipts name shops; the link needs a claim, the claimant's name or other document evidence.
- strong: the same party or an exact reference, and allocations that add up to the bank amount in a compatible currency.
- tentative: plausible but incomplete: amount only, uncertain name, partial or differing amount, unknown currency, or competing lines.
- none: no candidate plausibly paid this line.
- Never fill missing facts from the bank line. Without attached images, do not claim to have seen them.

Output: one decision per bank_id. Allocations use candidate item_ids and decimal amounts; an empty amount means supporting evidence only. Keep the reason to one or two sentences and state any amount difference.
