# PDF routing benchmark: 18 September 2026

The strict route is implemented, but this sample does **not** justify enabling
text-only processing for the current document collection.

Local preflight examined 264 PDF pages. Only four passed the initial structural
checks; 260 were routed toward vision. Rejection reasons overlapped: 257 pages
contained bitmap content, 49 had insufficient native text, 19 had hidden or
translucent text, nine had complex vector layouts, and six had garbled text.
Bitmap content includes logos and other images, not necessarily scans. The
strict policy deliberately treats all such content as potentially relevant.

The live benchmark used GPT-5.6 Sol through the existing ChatGPT subscription.
It compared all four eligible pages from four documents and exercised direct
vision on two image-containing pages from a fifth document. No customer review
state, source files, accepted decisions or active settings were changed.

| Four matched pages | Text route | Vision route |
| --- | ---: | ---: |
| Input tokens, including cached input | 61,923 | 74,865 |
| Cached input tokens | 10,880 | 43,520 |
| Output tokens | 2,520 | 1,999 |
| Cumulative model-call elapsed time | 236.3 s | 213.7 s |

Text used **17.3% fewer input tokens**, or **16.2% fewer input + output tokens**,
on those four pages. It was not faster in this run. Provider cache reuse differed
substantially, so raw token savings cannot be translated into the same cost or
subscription-allowance savings. Calls were sequential, with text before vision;
this small run is not a controlled latency benchmark.

All four pairs agreed on receipt count, invoice numbers, total and currency.
This includes blank values and is **not a human-verified accuracy score**.
All four text results still triggered the conservative checks: incomplete
receipts, reported limitations and/or currency without exact native-word
evidence. None qualifies for text-only use under the implemented policy.
Trying text and then falling back would therefore add cost on these pages.
The hybrid layout allowlist remains empty; unknown layouts go directly to vision.

All 10 model attempts completed and reported usage:

- Input: 174,601, including 76,160 cached input tokens.
- Output: 5,148, including 1,178 reported reasoning output tokens.
- Unknown attempts: 0. Application response-cache hits: 0.

The two risky pages used vision directly. Results cover **page extraction only**;
document assembly and later comparisons still use their existing evidence.

Raw results remain local in
`duplicated/benchmarks/pdf-routes-20260918/`: `plan.json`, `report.json`,
`page-*.json`, `token-usage.jsonl` and individual request logs. Instructions for
repeating the benchmark are in [PDF_ROUTING.md](PDF_ROUTING.md).

Recommendation: retain vision for this corpus. Expanding the cheaper route
requires human-checked examples and measured changes to the eligibility rules;
do not weaken the checks merely to produce a larger savings percentage.
