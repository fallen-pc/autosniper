# Non-Negotiable Rules

These rules are durable project law unless Ewan explicitly approves a change and the protected memory layers are updated on purpose.

1. Repo-local project memory is the operational source of truth. Session memory is not.
2. `project_memory/02_state/` is the only memory layer agents may update by default.
3. Resale estimates are governed by curves. Sold-car history informs hammer-bid strategy, not retail resale overrides.
4. Full listing URL is the unique identifier for listing lifecycle tracking.
5. Dataset contracts, tracked datasets, and curve contracts must stay machine-readable and validated from code-backed sources.
6. Protected memory layers must not change silently. Constitution, machine rules, decisions, and the manifest require explicit approval.
7. High-sensitivity files are not casual cleanup targets. If a task touches them, it must be intentional and state-backed.
8. The UI reflects business logic. It must not quietly redefine business rules because a page was easier to edit than the pipeline.
9. The model is a worker. The memory system must remain usable even if the model or launcher changes.
