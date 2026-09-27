Use the complete bank narration, including payment remarks, merchant/purpose words,
references and mixed-language text. Explain meaningful agreements and contradictions;
do not guess translations, identity aliases, claimant attribution or missing facts.

Candidate retrieval reserves exact invoice, receipt, booking, order, claim or payment
IDs, then merges up to 20 name matches and 20 exact-amount matches, with a maximum
of 40 distinct IDs. Within each route, description relevance (BM25) precedes date
proximity. If fewer than 10 remain, meaningful description matches top up to 10.
Retrieval scores and routes explain selection; they are not match confidence.

An exact reference is a complete specific identifier, not a substring, merchant name,
tax ID or recurring account number. Repeated references, conflicting currencies,
partial payments and invoice/payment-confirmation pairs need interpretation, not
automatic approval. Preserve every amount difference and avoid duplicate capacity.

Distinguish supplier payments from employee reimbursements. The bank recipient may
be a claimant while the receipt names a merchant or the company. Matching purpose
and amount makes a plausible candidate, not proof of who incurred the expense.
Seek explicit claim/report links; explain missing attribution and date discrepancies.
Group expenses only when evidence connects them, never merely because totals add up.

Use only candidate_ids for allocations. Other pieces in the complete source document
are context, not additional eligible IDs. If one is needed, flag further retrieval.
When search_incomplete is true, do not claim that no supporting evidence exists:
report only what the examined shortlist establishes. Reference overflow or equally
plausible unresolved alternatives require tentative. All proposals require human review.
