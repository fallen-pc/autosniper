# Recent Changes

- The repo already had first-generation memory files (`task_plan.md`, `findings.md`, `progress.md`, and `docs/ai_working_agreement.md`).
- Those files have now been folded into a layered memory architecture under `project_memory/`.
- Generated machine rules are now refreshed from authoritative code instead of being manually copied.
- Pre-commit and CI are being wired to fail when required memory is missing, stale, or edited in protected layers without approval.
