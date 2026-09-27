# Matching strategy review

Review date: 2026-09-26. This is an evaluation and proposed design, not a deployed
matching policy or an accuracy claim. The live piece path was inspected separately
from the historical experiments. Concurrent extraction, benchmark and UI work was
left intact. No new workflow model calls were made for this review.

## Recommendation

Use text-only matching over reviewed, source-linked facts. Keep broad pairwise
comparison in Python, generate only evidence-supported allocation possibilities,
check competition across the whole statement, and send unresolved relationships
to the subscription model in compact batches. Preserve explicit human approval.

At this corpus size, avoiding Python all-pairs comparisons is not the useful token
optimization. Model requests and repeated document context are the expensive part.
All-pairs comparison improves search coverage; it does not prove identity, repair
incorrect extraction, or by itself handle grouped payments correctly.

Removing images alone is insufficient. The current matching payload relies on the
original documents to recover facts that are absent or poorly typed in extraction.
Text-only matching should return an extraction/review issue when those facts are
missing. Original previews remain available to the reviewer; routine matching
does not need to send them to the model.

## What runs today

- `reconciliation/matching/retrieval.py:70`: scans every available bank/piece pair;
  reserves exact references, merges up to 20 name and 20 amount candidates, caps at
  40, and uses BM25 description hits only to top up a shortlist below ten.
- `dashboard/services/piece_match_jobs.py:99`: makes one model request per bank with
  candidates. It has no deterministic proposal route for clear matches.
- `dashboard/services/piece_matching.py:155`: supplies all pieces, original text and page
  images of every shortlisted parent document, plus related bank entries. Forty
  candidate IDs do not bound this context to forty pieces or forty pages.
- `dashboard/services/piece_match_jobs.py:23`: validates IDs, per-piece monetary bounds,
  currency, and bank coverage. Other evidence requirements largely live in prompts.
- `dashboard/services/final_review.py:197`: human approval applies additional source,
  extraction-acceptance, currency, capacity and discrepancy safeguards through the
  single final-review ledger.

The earlier batching and hybrid experiments are useful evidence, but their
experimental routing/global checks are not the current live runner.

## Reliability gaps

| Finding | Practical consequence | Required improvement |
| --- | --- | --- |
| Strong proposals are validated mainly by IDs and arithmetic | A plausible explanation can hide wrong attribution or an unsupported partial allocation | Validate evidence requirements and contradictions before assigning strong |
| New proposals are checked one bank at a time | Several strong proposals can consume the same receipt; approval catches the conflict later | Compare proposals together using current ledger reservations |
| Capacity belongs to piece IDs; economic links are absent | An invoice and its payment confirmation may each appear to provide another expense amount | Add explicit, source-supported common-obligation links |
| Individual exact amounts drive one retrieval route | Groups and instalments depend on incidental name/reference/text retrieval | Generate supported group and instalment hypotheses explicitly |
| Description retrieval only tops up short lists | Weak amount hits can crowd out a useful description candidate | Independent retrieval routes, tie preservation and expansion |
| Compact model pieces omit acceptance and limitations; boundary state is hardcoded resolved | The text-only model may receive facts without their uncertainty | Preserve field provenance, acceptance, limitations and unresolved boundaries |
| Party roles, reference namespaces and monetary roles are insufficiently structured | Claimants can be confused with merchants; unrelated reference values can collide | Typed evidence with unknown values retained |

Two small checks of the actual `validate_result` function reproduced the proposal
gaps: a strong 100 allocation from a 200 piece passed despite no instalment basis
and conflicting party/direction; two banks each allocating 100 from one 100 piece
also passed. These were isolated function checks, not end-to-end approval tests.
The final ledger **does** block unaccepted extraction and same-piece over-allocation.
The defect is misleading proposals and reliance on later human intervention, not
a bypass of those existing ledger checks.

`search_incomplete=False` means the implemented retrieval routes omitted none of
the candidates they found. It does not establish that all real support was found.
An absent claimant link, an unrepresented group, or an extraction error can still
hide a true relationship.

## Measured evidence

Reproduction artifacts for this review are under the ignored directory
`.tools/matching-strategy-review/`. Customer records remain outside tracked docs.
The aggregate figures below describe saved snapshots, not a fresh active-workspace
run and not adjudicated matching accuracy.

| Offline replay using current retrieval | Bank entries | Pieces | Pair comparisons | Observed runtime | Selected links | Entries with omissions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Historical full-statement monetary/claim records | 240 | 181 | 43,440 | 2.19 s | 1,626 | 58 |
| Saved live-piece snapshot | 240 | 252 | 60,480 | 2.80 s | 1,867 | 98 |

Both runs used Python and made zero model calls. Timings are single observations,
not latency guarantees. The saved live snapshot omitted 3,467 eligible pair links
under the current route quotas; this is not a count of missed correct matches.

Constructing parent-document context from that live snapshot would yield 3,544
image appearances across per-bank payloads, representing 269 distinct images.
Forty-one bank payloads would exceed the 40-image limit. These are potential payload
exposures, not images actually sent or measured image-token consumption. Saved
suggestions from that snapshot include 41 size-limit failures and 38 currency
validation failures. Those outcomes motivate payload and evidence changes; they
do not establish that removing images would make the proposals correct.

The same snapshot has date facts on 250 of 252 pieces, but the current parser
recognizes a date on only 27. Unhandled forms include slash-separated dates,
timestamps and month-only periods. Normalize unambiguous dates with documented
locale rules; retain periods and ambiguous dates as such instead of inventing a day.
The median request would also repeat 130 related bank entries because relevance
is inferred through parent-document overlap.

The current retriever also retained all expected pieces in the 20 positive
synthetic cases and both seven-way ambiguity sets. This is a small legacy fixture
coverage check, not precision measurement or proof of grouped-allocation logic.

The earlier real 240-line experiment provides actual reported matching usage:

| Historical strategy | Matching calls | Input + output tokens |
| --- | ---: | ---: |
| 20 bank lines per call | 12 | 445,618 |
| 40 bank lines per call | 6 | 295,635 |
| Python routing + ambiguous batches | 7 | 296,393 |

Forty-line batching used 33.7% fewer matching tokens in that experiment. These
figures exclude separate source verification and contextual review. The hybrid
had one invalid response affecting twenty entries. There are no independently
adjudicated real labels establishing which strategy was more accurate. Model
agreement and the number of strong suggestions are not ground truth. See
[the experiment report](MATCHING_EXPERIMENTS.md) for full accounting and caveats.

Separately, the available project `piece_matching` stage log records 190 completed
`gpt-5.6-sol` attempts on September 19, with 9,192,401 input and 54,991 output tokens
(9,247,392 combined), zero unknown-usage attempts and zero whole-response cache
hits. Its 1,755,392 cached input tokens are already included in input. This is the
available stage-log total, not a whole-workflow total, not an image-token total,
and not independently established as the exact run behind the copied suggestions.
The audit JSON records the log path and hash. No new usage was incurred by the
offline replay.

Reproduce the isolated checks with:

```text
python .tools/matching-strategy-review/replay_retrieval.py
python .tools/matching-strategy-review/validator_reproduction.py
```

The saved live input is `review/matching-images-benchmark/previous-evidence.json`,
copied at 2026-09-26T12:01:42Z. Input/code hashes and exact capture time are in
`benchmark-audit.json`. The validator reproduction loads the actual function AST
and helpers because the host lacks a dashboard import dependency; it is not an
end-to-end integration test. The separate prepared image/text benchmark has no
comparison results at this audit snapshot and provides no accuracy evidence yet.

## Proposed matching contract

Each payable item needs persistent identity and a compact fact record:

- Original piece/document IDs, source hash, extraction revision, source locations,
  acceptance state and unresolved limitations.
- Amount, explicit currency, and monetary role: payable obligation, schedule
  control total, subtotal, payment evidence or context only. Keep printed amounts
  separate from proposed allocations.
- Parties with roles: supplier, employee claimant, beneficiary and merchant.
  Verified aliases/account links carry their own provenance; an account identifier
  may establish party identity but is not a unique transaction reference.
- Typed references with issuer/scope when known, and dates with roles such as
  invoice date, service period and actual payment date.
- Supported claim/batch links, instalment terms and relationships between evidence
  records describing the same obligation. Unknown relationships stay unresolved.

Do not infer one obligation merely from equal names, amounts and dates. Different
receipts can represent different purchases; an invoice and confirmation can
represent one. Byte-identical deduplication and economic-event identity are
different checks. Preserve original piece IDs and historical reservations when
adding obligation relationships; use a versioned, auditable migration.

## Algorithms and decision stages

### 1. Compute broad comparisons locally

For the present hundreds of records, compare every bank entry with every piece
using Python. Precompute normalized fields once. Keep a feature vector and explicit
contradictions, rather than one opaque score:

- Exact, scoped reference agreement; preserve leading zeros and significant
  punctuation. Different reference types must not become equal by value alone.
- Party-role agreement, approved alias/account links, and separate fuzzy-name
  retrieval using character similarity or anchored truncation.
- Currency, direction/transaction role, full amount, remaining amount, dated facts
  and meaningful description terms. Unknown is distinct from disagreement.

Name similarity and BM25 are retrieval aids. Equal amount plus shared generic words
does not establish a payment. Role-aware dates can rank candidates, but no default
30-day exclusion is introduced. Locale-ambiguous dates remain unresolved.

For larger corpora, use the union of several indexes or blocking rules, preserving
exact-reference alternatives and measuring recall. Splink documents this
[multiple-rule blocking approach](https://moj-analytical-services.github.io/splink/topic_guides/blocking/blocking_rules.html).
At the current size, retain broad local coverage and optimize model payloads first.

### 2. Generate supported allocation possibilities

For a direct full payment, require accepted usable facts, compatible currency,
an explicit payable amount and attributable identity or a specific compatible
reference, with contradictions and competitors checked. It becomes a proposal for
human review, never an approval.

For a grouped payment, search only inside a source-supported claim, remittance or
batch group. Use bounded subset-sum over integer currency units. A meet-in-the-middle
search is an option for larger bounded groups; record incomplete search if a
resource limit is reached. Multiple feasible subsets stay ambiguous. Do not search
arbitrary subsets across unrelated receipts or invent a group because amounts add up.

For instalments, require supported terms or an explicit payment/invoice link and
an interpretable allocation basis. A 100 bank payment and a 200 receipt do not by
themselves establish a 100 instalment. Approved remaining balances constrain a
proposal; they do not prove it.

Handle returns, reversals, retries and refunds as evidenced transaction
relationships. Equal opposite amounts alone are insufficient to cancel payments.
Missing currency, unknown monetary roles and unexplained discrepancies remain
unresolved/contextual. Cross-currency allocations remain unresolved/contextual under
the existing scope; any conversion workflow requires a separately agreed policy.

Oracle's reconciliation design separately represents
[one-to-one, grouped and many-to-one matching with grouping attributes](https://docs.oracle.com/en/cloud/saas/financials/26b/fairp/reconciliation-matching-rules.html).
That supports treating these as different rule families instead of asking a single
similarity score to explain every payment pattern.

### 3. Check the whole statement before assigning confidence

Build a graph connecting banks to eligible obligations and allocation possibilities.
Use current approved reservations, including stale historical reservations, when
checking available capacity. An ambiguous component is a connected set of competing
transactions and evidence.

The lean first version can simply detect conflicts and downgrade all unresolved
competitors. An optimizer is not required to prevent contradictory strong proposals.

For later disambiguation:

| Problem | Suitable method | Important restriction |
| --- | --- | --- |
| Verified one-to-one possibilities | Maximum-weight bipartite matching or min-cost flow | Allow unmatched entries; do not force every row to pair |
| Evidenced grouped/instalment possibilities | CP-SAT selection of prevalidated hypotheses | Solver selects supported allocations; it does not invent amounts |
| Small explicit reimbursement group | Exact subset-sum enumeration | Preserve multiple valid subsets and enforce evidence links |

[OR-Tools documents assignment using minimum-cost flow](https://developers.google.com/optimization/flow/assignment_min_cost_flow)
and [integer constraint solving with CP-SAT](https://developers.google.com/optimization/cp/cp_solver).
These are suitable implementation tools, not evidence that any optimized result
is factually correct.

For CP-SAT, represent each supported hypothesis by a Boolean choice. Constrain at
most one mutually exclusive resolution per bank, and constrain each obligation's
total proposed allocation to its remaining capacity. Multi-bank hypotheses consume
every included bank. Use exact minor currency units derived from Decimal, and
keep distinct currencies in distinct constraints. Non-monetary attachments consume
no payable capacity.

Keep the unmatched option. Do not maximize the number or value of matches ahead of
evidence quality. A stable-ID tie break is for display reproducibility, never a
reason for confidence. Check alternative feasible solutions by excluding selected
hypotheses; equal or nearly equivalent alternatives remain ambiguous. A solver
timeout or unproven optimum cannot establish unique support.

### 4. Ask the model only about unresolved relationships

Send compact text facts, relevant source excerpts with locations, explicit
limitations, candidate alternatives, related payments, reservations and permitted
allocation hypotheses. Deduplicate shared records within each request. Never omit
contradictory facts merely to fit a context budget; expand or return unresolved.

Batch by competing evidence and payload size. A weak common-amount link can connect
much of a statement, so do not send an unlimited connected component. Partition
bounded requests while retaining outside-batch competitors and enforce global
checks after collecting results. The historical 20/40-line results are starting
points for experiments, not universal batch sizes.

Require structured answers: bank ID, hypothesis IDs, cited input fact IDs, unresolved
questions, contradictions and a short explanation. Python checks cited IDs, coverage,
monetary rules and evidence status. Semantic plausibility alone cannot promote
unsupported identity, grouping or instalment facts. Empty results and failed calls
remain unresolved; they never establish absence of support.

If source text is inadequate, return to extraction review. A future explicitly
enabled source-repair mode could inspect a specific page once and save the corrected
facts; that is separate from routine matching. This proposal defaults to no images
in matching, consistent with the stated preference.

Cache by source/extraction revisions, candidate universe, relevant competitors,
ledger reservations, prompt/schema and model. Changes to evidence links or ledger
capacity must invalidate affected components. Record every `codex exec` attempt,
stage/model totals, zero new usage for cache hits, and unknown usage explicitly.

### 5. Use transparent rules before learned confidence

Start with explicit rule tiers and named unresolved reasons. Do not present a
weighted sum as a percentage probability. Amount, name and description overlap
often repeat the same evidence; adding all three independently can exaggerate it.

With enough representative labels, evaluate Fellegi-Sunter or a calibrated
supervised pair scorer. Splink explains both
[agreement likelihoods and the independence assumption](https://moj-analytical-services.github.io/splink/topic_guides/theory/fellegi_sunter.html)
and [adjustments for common versus rare values](https://moj-analytical-services.github.io/splink/topic_guides/comparisons/term-frequency.html).
Those ideas are useful, but there is insufficient labelled evidence here to claim
a calibrated score today. Pair scoring also does not replace global allocation rules.

Embeddings are an optional later description-retrieval aid. They do not validate
amounts, currencies, identities or grouped capacity, and are unnecessary for the
first redesign.

## Verification before changing the default

1. Freeze a corpus and source-adjudicate real outcomes, including unsupported and
   ambiguous cases. Reviewers must inspect evidence outside the current shortlist
   so retrieval omissions can be discovered. Model outputs are not gold labels.
2. Cover direct payments, repeated amounts/names, claimant/merchant differences,
   grouped claims, documented instalments, invoice/receipt pairs, returned/retried
   payments, missing currency, old documents and incorrect extraction. Label valid
   alternatives and ambiguity rather than selecting an arbitrary winner.
3. Compare current policy, image-free current policy, deterministic rules with
   conflict checks, and the proposed text-only hybrid on the same evidence. Keep
   extraction and retrieval fixed for the image ablation; otherwise the effect of
   images cannot be isolated. Evaluate extraction-quality changes separately.
4. Measure candidate recall and complete-group recall, wrong strong proposals,
   allocation validity, abstention, reviewer corrections, unresolved failures,
   latency and reported tokens by stage/model. Include retries and source repair;
   do not present matching-only usage as end-to-end usage.
5. Test order independence, fresh competing payments, edits after approval,
   stale reservations, ties, incomplete retrieval and invalid model responses.
   Zero accounting-invariant failures is required. Predeclare acceptable quality
   thresholds before tuning; use a holdout split by obligation/project or period
   to avoid leakage between related documents.

The implementation order should be: preserve evidence uncertainty and add proposal
guards; add global conflict checks; introduce compact text-only batches and local
proposals; then add group/instalment optimization where labelled cases justify it.
Keep the existing human ledger, migration history, source binding, previews,
discrepancy flags and export rules throughout. Do not rescore old approvals silently.
