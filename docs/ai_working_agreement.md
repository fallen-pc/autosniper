# AI Working Agreement for AutoSniper

This file is now a compatibility summary. The authoritative memory system lives under `project_memory/` and is loaded through `project_memory/memory_manifest.yaml`.

## Start Here

Before non-trivial work:

1. Prefer `.\scripts\start_ai_task.ps1 -TaskKind <kind> -Intent <read|write> ...` as the front door
2. Read the returned context bundle instead of relying on chat memory
3. If doing normal upkeep, only update `project_memory/02_state/`
4. If changing constitution, machine rules, decisions, or the manifest, do it intentionally and set `AUTOSNIPER_MEMORY_WRITE_APPROVED=1`

## Source Of Truth Order

1. Explicit user instruction in the current conversation
2. Files required by `project_memory/memory_manifest.yaml`
3. This summary plus `task_plan.md`, `findings.md`, and `progress.md`
4. Current code and tests
5. Global workspace memory
6. Chat recollection alone

## Current Focus

- verify profit determination accuracy
- identify what blocks safely adding more curves in Curve Builder V2

## Current Boundary Reminder

High-sensitivity files are still high sensitivity. Use `project_memory/02_state/active_boundaries.md` for the current boundary list instead of guessing from memory.
