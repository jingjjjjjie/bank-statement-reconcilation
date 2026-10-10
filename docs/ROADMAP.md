# TODO

- [ ] **Folder-based possible match groups** — Add a second matching pass, initially for bank transactions without a convincing match, to find folders whose names contain an amount.
  - Treat the folder amount as a retrieval hint, never as extracted evidence or proof of currency.
  - Examine the contained supporting pieces together: compare actual amounts, currency, payees, dates and references with candidate bank payments.
  - Suggest groups of separate expenses whose amounts support a payment (for example, receipts of MYR 200 + MYR 150 for a MYR 350 payment). Avoid double-counting an invoice and its payment proof or duplicate documents.
  - Show a compact “Possible group · 2 documents · MYR 350” card. Expansion shows its pieces and the reason; reviewers can select the group and remove individual pieces before confirming.
  - If only the folder name matches, label it “Folder amount matches; contents unverified.” Keep missing or conflicting facts unresolved; never fill extracted amounts from a folder name.
  - Preserve original evidence links, existing allocation/capacity validation and the single approval ledger. Groups remain proposals until explicitly confirmed.
