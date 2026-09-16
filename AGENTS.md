for now keep everything clean and concise, for coding practices, please keep the code to be minimal ,readable, and leave short and concise comments for every block.

Use Python for development.

Default all workflow LLM reasoning and vision to `gpt-5.6-sol` unless explicitly overridden for a benchmark or by the user.

Keep duplicate-review output in this Development workspace under `duplicated/`, not inside the original supporting-document folder. Preserve original locations in the manifest.

Whenever the application or workflow requires LLM reasoning or vision, use `codex exec` with the existing ChatGPT subscription login. Do not use API keys or a separate paid API connection unless the user explicitly changes this preference. Python should handle deterministic extraction, hashing, validation, and workflow state. Use structured model output, attach images for vision, and record incomplete or failed calls as unresolved. Never treat model output as admin approval to delete files.
