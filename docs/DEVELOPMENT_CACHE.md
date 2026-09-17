# Development / testing mode

Use the switch in **Settings**. New workspaces default to OFF; the local choice
is saved in `config/development.local.json` (ignored by Git).

- **ON:** shows testing defaults and decision tools, shares successful model
  results across reviews, and saves generated outputs and human decisions.
  Enabling it also captures the active review's existing outputs and model cache.
- **OFF:** hides the tools and rejects development actions. Shared-cache reads
  and writes stop. Saved shared data and ordinary review history remain intact.
  Normal per-review resumability continues.

Stop an active content-review batch before changing the switch.

The shared cache lives under `duplicated/development-cache/`:

| Folder | Contents |
| --- | --- |
| `model-requests/<request hash>/` | Prompts, schemas, validated results and attempt logs |
| `runs/<run id>/token-usage.jsonl` | New attempt events and zero-usage cache hits; missing usage remains unknown |
| `projects/<source hash>/snapshots/` | Versioned artifact indexes with original paths and SHA-256 hashes |
| `projects/<source hash>/decisions/history/` | Human decision snapshots, including later undo states |
| `projects/<source hash>/decisions/latest.json` | Latest choices available for explicit replay |
| `projects/<source hash>/decisions/preset.json` | Choices pinned by **Remember**, retained through undo |
| `objects/<hash prefix>/<hash>` | Deduplicated generated output bytes |

Model reuse requires the same prompt, schema, model, reasoning setting and image
bytes. Failed responses are retained for diagnosis but are not reusable results.
Historical token logs captured from existing reviews remain in output snapshots;
they are not counted again as new attempts.

Human decisions are never applied automatically. **Apply remembered decisions**
requires a reviewer name. Exact decisions match original paths and file hashes;
content decisions also require matching comparison evidence and configuration.
Old content presets without evidence are retained but cannot be replayed.

Output snapshots are archives, not automatic restoration of live workflow state.
Original document locations remain in the manifest. The cache is local testing
data, not a substitute for a separate backup.
