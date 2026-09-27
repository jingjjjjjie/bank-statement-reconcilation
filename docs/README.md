# Documentation

Start with [architecture](ARCHITECTURE.md): where code lives, dependency rules and how to make common changes.

| Folder | Read it for |
| --- | --- |
| [workflow/](workflow/) | How each step works today: [workflow diagrams](workflow/WORKFLOW.md), [PDF routing](workflow/PDF_ROUTING.md), [bank extraction](workflow/BANK.md) and [workbook style](workflow/BANK_WORKBOOK_STYLE.md), [final comparison rules](workflow/FINAL_COMPARISON.md), [matching retrieval](workflow/MATCHING_RETRIEVAL.md). |
| [operations/](operations/) | Running safely: [process cancellation](operations/PROCESS_CANCELLATION.md), [token accounting](operations/TOKEN_ACCOUNTING.md), [development cache](operations/DEVELOPMENT_CACHE.md). |
| [ui/](ui/) | Dashboard rules and audits: [UI guidelines](ui/UI_GUIDELINES.md) (required for UI changes), [final report UI review](ui/FINAL_REPORT_UI_REVIEW.md), [earlier UI audit](ui/UI_REVIEW.md). |
| [benchmarks/](benchmarks/) | Measured results: extraction, instructions, PDF routing, matching images and matching experiments. |
| [reviews/](reviews/) | Design reviews of the extraction flow, piece pipeline and matching strategy (historical context). |

Local, private notes belong in `docs/local/`, which Git ignores.
