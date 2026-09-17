# Matching experiments and recommended design

Experiment label: 20260918. These are research results, not deployed matching behavior or approved customer matches.

## What was actually tested

30 subscription-based `codex exec` calls using `gpt-5.6-sol`, structured JSON, two concurrent calls at most, and durable per-attempt token accounting. Nine configurations used the same 40 labelled synthetic bank cases. These are 40 distinct synthetic cases, not 360 independent examples. Twenty real bank lines were also tested twice using two representations of the supporting facts. The cases cover references, names, wrong/unknown currency, opposite direction, missing totals, seven-way ambiguity, grouped claims (including seven receipts), instalments, conflicting payments, old invoices, claimant versus merchant, complementary evidence, and hostile document text.

Separately audited the real 240-line statement and 69 available supporting records from single-unit files. Verified the statement's original bytes match the saved bank CSV's source hash. Excluded 61 multi-unit files because their assembly was not ready at the audit snapshot. No approved real matching labels exist, so no real-world accuracy percentage is claimed. Automatic approval review initially blocked the two real-data model calls. The user then explicitly authorized both batches through the existing ChatGPT/Codex subscription, and both completed without modifying any review decisions.

Artifacts, including exact model inputs, responses, errors and token events, are saved under `duplicated/benchmarks/matching-20260918/`. `analysis.json` re-scores saved responses with a single evaluation rule. Customer facts remain in that ignored directory.

## Measured results

Each row processes the same 40 cases. Input counts include cached input; cached tokens and reasoning tokens are also reported separately in the raw logs and must not be added again. Token figures below are reported usage, not estimates or currency costs.

| Configuration | Calls | Input tokens | Output tokens | Incorrect confident proposals before Python checks |
|---|---:|---:|---:|---:|
| Fixed 5-line / top-5 batches | 8 | 133,765 | 2,736 | 4 |
| Fixed 10-line / top-5 batches | 4 | 73,535 | 2,388 | 4 |
| Fixed 20-line / top-5, shuffled order | 2 | 38,684 | 2,062 | 4 |
| 10-line maximum, expanded ties + conflict context | 5 | 87,600 | 2,300 | 0 |
| 20-line maximum, expanded ties + conflict context | 2 | 43,266 | 2,136 | 0 |
| 40-line maximum, expanded ties + conflict context | 1 | 28,495 | 1,886 | 0 |
| Local factual routing, remaining ambiguous cases batched | 1 | 20,372 | 1,060 | 0 |

An unshuffled plain 20-line run initially had zero incorrect proposals, but shuffling separated competing transactions and exposed four errors. Batch size alone is not the safeguard. The global Python allocation check downgraded all four oversubscribed proposals to review. It also preserved legitimate 40+60 instalments against a 100 invoice.

The contextual and hybrid runs correctly identified all 20 positive cases and abstained on all 20 ambiguous/negative cases. Strict three-way status agreement was 38/40: the model classified two unrelated-party amount coincidences as `no_candidate` instead of the fixture's `review`. Both outcomes abstain from matching. This distinction is retained in the results; it is not silently scored as exact status agreement.

The hybrid routed 24 cases locally (16 proposals awaiting human approval and 8 with no indexed candidate), leaving 16 for one model call. Its reported input plus output was 52.8% below the improved 20-line strategy and 29.5% below the 40-line strategy. It did not materially improve wall-clock time over the 20-line run in this small test: about 35 seconds each. The 40-line call took about 45 seconds. Runtime and cache behavior can vary.

Total experiment usage including the two real calls: 589,609 input tokens, of which 127,488 were reported cached input; 22,035 output tokens, with 4,829 reported reasoning output tokens. 30 attempts, zero unknown-usage attempts, zero whole-response cache hits. Synthetic calls used `matching_benchmark`; the two real calls used `matching_real_benchmark`, with 63,110 input and 2,700 output tokens. All calls used the same model. Sixteen local regression checks passed, covering the experimental logic and the existing receipt allocation safeguards.

## Findings from real data

- A claim schedule is currently represented as one 2,030 total, but its source has seven payee rows. Reading the existing prepared source cells recovered the seven amounts, which sum exactly to 2,030. Six had bank candidates agreeing on amount and normalized full or visibly truncated name. These are source-checked candidates, not approved matches; the seventh requires more investigation.
- Therefore the matching unit must be a **payable item**, not necessarily a file or a physical receipt. Ordinary invoice product lines stay within one payable item; a schedule paying seven different people has seven payable items. Keep the parent total as a control, not an eighth expense.
- Current piece-level extraction does not consistently preserve payee, date, reference and monetary role per piece. Unit-level lists must not be copied to every piece in a multi-receipt image. Fix the extraction contract before treating this as a production matching input.
- Three audited records lacked currency, five lacked amounts, and five lacked attributable parties. Unknown facts must remain unknown. The wage claim with total 25 and blank currency can be shortlisted, but needs explicit currency confirmation before allocation.
- Broad shared-word name matching and generic references produced 1,049 candidate links and 86 ties at the fifth position. More specific whole-name matching and identifier filtering reduced these to 177 links and two ties. This measures reduced noise, **not** real-data recall: missing aliases, excluded documents and incomplete extraction can still hide matches.
- In the fixtures, top five dropped two complete seven-way ambiguous candidate sets. Explicit grouping kept a seven-receipt payment representable as one candidate. Never search every subset of all documents: only combine a small, evidenced claimant/reference group, and flag oversized groups for dedicated review.

## Real model comparison

Both calls contained the same 20 outgoing bank entries. The document-total representation supplied 17 unique candidates and used 26,811 input / 1,396 output tokens. The payable-row representation supplied 23 unique candidates and used 36,299 input / 1,304 output tokens. Durations were approximately 49 and 40 seconds. More attributable evidence costs context; it should not be dropped merely to minimize a token count.

The original aggregate representation proposed six links to the 2,030 schedule and omitted the seventh bank line from its shortlist. Critically, its explanations claimed individual allocations such as 750 and 600 even though those amounts appeared only on the bank side of the supplied records. Checking the original cells showed they happened to agree, but the model had not been supplied those supporting row amounts. Global capacity arithmetic alone would not catch this unsupported inference.

With explicit payee rows, all seven proposed links selected the corresponding row ID and printed amount. The recovered seventh involved a visibly truncated surname in the bank record. This supports row-level retrieval and model-assisted name review, not automatic identity approval. The remaining thirteen bank lines have not all been independently adjudicated, so these runs do not establish a 20-line accuracy score. Generic amount-plus-purpose proposals also need an attributable claimant/payee link before acceptance.

A required production check follows: mark totals as payable-item amounts versus schedule control totals. A control total must never be used as arbitrary capacity for individual bank payments. Require an explicit per-payee amount, a supported group allocation, or documented instalment basis. Do not backfill supporting amounts from the bank statement. Reject or flag a proposal whose cited supporting fields cannot substantiate its allocation.

## Recommended logic

1. **Prepare attributable payable items.** Each has stable item/document IDs, an explicit payable-versus-control-total role, source pages or cells, payee/claimant versus merchant roles, currency, amount, dated facts with their roles, references, and remaining amount. Attach companion invoice/confirmation evidence to one expense when justified. Do not infer these relationships from filenames or coincidental totals.
2. **Retrieve in Python using indexes.** Union reference, account/party and amount candidates. Normalize honorifics, spacing and name order; keep uncertain aliases explicit. Treat dates as ranking evidence rather than an irreversible 30-day filter. Currency/direction conflicts need separate handling; unknown values are not matches or automatic exclusions.
3. **Use five as an initial shortlist, not a hard cutoff.** Preserve ties, strong-reference alternatives and plausible groups. The experimental expansion cap of twelve is a resource limit, not proof that other candidates are invalid. If it is reached, mark retrieval incomplete and use an expanded search or manual review; never select arbitrarily.
4. **Route obvious cases locally to the human queue.** Unique verified amount plus a substantive reference or attributable name can become a proposal without model reasoning. No model or deterministic rule grants approval. No indexed candidates means “none found yet,” especially while extraction is incomplete.
5. **Batch only ambiguous cases.** Start around 20 bank lines, allow up to 40 for compact cases, and split on evidence size rather than row count alone. Twenty is not a measured universal optimum. Group bank lines sharing plausible evidence, and include relevant outside-batch competing transactions. Store each supporting record once per batch. Store repeated bank context once as well. The prepared real-data row payload shrank from 59,075 to 41,586 JSON characters by deduplicating context without dropping facts; this representation change was checked locally, not tested in another real-data model call.
6. **Require structured proposals.** Return bank ID, selected item/group IDs, explicit allocations, evidence references, reasons, conflicts and unresolved fields. The experiment used selected candidate IDs and Python-derived fixture allocations; explicit free-form model allocations and production-scale group search need separate validation before deployment. Escalate only unclear source facts to an original-image/text check, rather than attaching every original to every match request.
7. **Validate globally after all batches.** Check IDs and batch coverage, source-backed allocation amounts (not bank-derived guesses), exact decimal arithmetic, monetary roles, currencies, already accepted reservations, duplicate economic events and competing new allocations. If two equally supported payments demand more than one receipt can cover, flag both; do not award it to whichever batch finishes first. Keep amount differences visible and require review. Cache by evidence, allocations and relevant competing-candidate revisions, not just one bank row.
8. **Review and export from one ledger.** Keep the agreed statement-review and unmatched-supporting pages. All approvals are human actions with undo/history. Matching suggestions do not change originals or the bank master. Unresolved support remains exportable with explicit flags.

## Limits and next verification

This supports the hybrid architecture and exposes specific failure modes. It does not establish production accuracy or prove zero errors. Synthetic labels are known, but the corpus is small, each variant ran once, and changes to retrieval/context mean not every row is a perfectly controlled batching-only comparison. The 10/20/40 refined runs use the same shuffled case set and context policy. Real source checks cover one seven-payee schedule; they are not a full adjudicated statement.

Before deployment: finish assembly, add payable rows and attributable matching fields, label a representative real sample including aliases and grouped payments, then measure candidate recall, false proposals, abstention, allocation correctness and usage. Repeat with shuffled order and fuller evidence. Keep model-off local proposals available and do not implement a model call for every bank line.

Reproduce the synthetic experiments inside the configured container:

```text
python -m scripts.benchmark_matching <new-output-directory>
python -m scripts.benchmark_matching <new-output-directory> --specific --shuffle 17 --variants 20:5:0:0,10:adaptive:1:1,20:adaptive:1:1
python -m scripts.benchmark_matching <new-output-directory> --specific --shuffle 17 --variants 40:adaptive:1:1
python -m scripts.benchmark_matching <new-output-directory> --specific --shuffle 29 --hybrid --variants 20:adaptive:1:1
python -m unittest tests.unit.test_matching_benchmark tests.unit.test_receipt_matching
```

Exact original request JSON and the effective prompts in the saved model cache are authoritative for replay: the experiment harness was refined between runs. The current harness includes richer competitor context than the earliest exploratory run. Live execution uses the existing ChatGPT login and records every attempt; it does not require an API key.

The user selected six parallel requests for the next application batch; `config/review_config.json` now saves `max_parallel: 6`. The comparative synthetic runs used two concurrent requests so their timing remains comparable; the two authorized real tests ran sequentially.

## Full 240-line comparison

The subsequent authorized experiment covers all 240 bank entries using a frozen snapshot of 136 supporting documents, 181 monetary/claim records (including 53 explicit spreadsheet payee rows), and a shared contextual follow-up for 37 other documents. Model: `gpt-5.6-sol`, six parallel workers, structured output and global allocation checks. No proposals were approved or written to live matching state.

| Matching strategy | Matching calls | Input tokens | Output tokens | Matching elapsed | Checked strong | Tentative | None found |
|---|---:|---:|---:|---:|---:|---:|---:|
| 20 lines per call | 12 | 429,970 | 15,648 | 160.7 s | 40 | 44 | 156 |
| 40 lines per call | 6 | 283,060 | 12,575 | 62.9 s | 37 | 38 | 165 |
| Python routing + 20-line ambiguous batches | 7 | 285,731 | 10,662 | 56.5 s | 30 | 67 | 143 |
| Python matching only | 0 | 0 | 0 | 0.233 s total | 18 | 134 | 88 |

The hybrid handled 112 lines locally (23 unique payee-row proposals and 89 without indexed candidates) and sent 128 to the model. One model response failed candidate-ID validation, leaving 20 lines unresolved and tentative. Its tokens are included; there was no retry in this benchmark. This prevents interpreting the hybrid's lower strong count as a clean accuracy comparison.

Matching token/time figures exclude source verification and contextual review. The initial 20-line run used another 18 source-check calls (309,136 input / 7,016 output tokens, 205.3 seconds) and one contextual call (27,727 / 664 tokens, 18.0 seconds). The 40-line variant needed eight new source-check calls (129,859 / 2,029 tokens, 35.7 seconds); subsequent variants reused prior checks. Python matching itself used no model, but its **checked** count relies on those shared model source checks. All experiments together made 52 calls with 1,465,483 input and 48,594 output tokens; no attempt has unknown usage. Cached input of 304,768 is already included in input; reasoning output is already included in output.

Elapsed matching time comes from saved first-start/last-finish timestamps, accounting for parallel overlap. Measured later end-to-end times, including incremental verification and report writing, were 98.076 seconds for 40-line batches, 56.359 seconds for hybrid, and 0.233 seconds for Python. Stage timestamps and monotonic total timers use different clocks. The original baseline had no end-to-end timer; do not infer one or include pauses as model runtime. These are single-run observations, not repeatable latency guarantees.

The 40-line run reduced matching input by about 34% and elapsed matching time by about 61%, but the strategies disagree on returned/retried transfers, shortened payee names and unresolved multi-page invoices. Only 26 identical strong allocations are shared across the three model-assisted runs; 17 other lines have a strong proposal in at least one run without that agreement. More strong proposals does not establish higher accuracy. Source checks are model judgments, not human ground truth. Document assembly is still incomplete; no candidate does not establish missing support.

Current conclusion: 40-line batches are worth retaining as a lower-cost option for review. The hybrid needs invalid-response recovery and better grouping of competing payments before a fair follow-up comparison. Resolve reversal relationships and receipt boundaries before relying on any strong count.

Private local records: `duplicated/benchmarks/full-statement-240/STRATEGIES.md`, `strategy-comparison.json`, `strategy-total-usage.json`, `strategy-comparison.csv`, and `disputed-strong-candidates.json`. Every variant retains per-line reasons, source locations, request/result JSON, durable attempt logs and token usage. These private artifacts are ignored by Git; this document records aggregate findings only.

Reproduce with `python -m scripts.test_statement_matching --work <review> --bank <master.csv> --statement <original.pdf> --output <new-output> --workers 6`, then `python -m scripts.compare_statement_strategies <new-output> --workers 6`. Use `--report-only` on the comparison command to refresh reports and timing from saved evidence without model calls. Reusing an output directory resumes its frozen experiment; use a new directory for a new corpus.
