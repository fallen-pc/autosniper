# AutoSniper Codex Instructions

When a new Codex chat is told to "refer to AGENTS.md", use this file as the operating contract for this repo.

## Repo Root

Work in the nested AutoSniper checkout:

```text
C:\Users\Anonymous\Desktop\autosniper-main-sandbox\autosniper-main-sandbox
```

Do not treat sibling folders under `C:\Users\Anonymous\Desktop\autosniper-main-sandbox` as part of this repo.

## Start Every Non-Trivial Task

1. Read the repo-local project memory before acting.
   - Preferred bootstrap:
     ```powershell
     .\scripts\start_ai_task.ps1 -TaskKind write -Intent write -NoLaunch
     ```
   - If already inside Codex and not using the launcher, at minimum read:
     - `project_memory/memory_manifest.yaml`
     - `project_memory/00_constitution/non_negotiable_rules.md`
     - `project_memory/02_state/current_status.md`
     - `project_memory/02_state/open_issues.md`
     - `project_memory/02_state/next_actions.md`
     - task-specific files from `project_memory/01_machine_rules/` and `project_memory/03_decisions/`
2. Inspect current repo state before changing files:
   ```powershell
   git status --short
   ```
3. Preserve user/runtime changes. Do not revert unrelated edits.

## Memory Update Rule

For every meaningful source, pipeline, UI, governance, or business-rule change, update repo-local state memory in the same work slice.

Default writable memory path:

```text
project_memory/02_state/
```

Most small completed work should add one concise dated bullet to:

```text
project_memory/02_state/recent_changes.md
```

Use `current_status.md`, `open_issues.md`, or `next_actions.md` only when the current truth, remaining blocker, or next action actually changes.

Do not edit protected memory unless the user explicitly approves it:

```text
project_memory/00_constitution/
project_memory/01_machine_rules/
project_memory/03_decisions/
project_memory/memory_manifest.yaml
```

Protected-memory edits require:

```powershell
$env:AUTOSNIPER_MEMORY_WRITE_APPROVED='1'
```

## Verification Rule

Run focused tests for the touched area, then the normal checks when the change can affect pipeline behavior, valuation, governance, or committed repo state:

```powershell
venv\Scripts\python.exe -m pytest -q
venv\Scripts\python.exe scripts\readiness_smoke.py
venv\Scripts\python.exe scripts\governance_checks.py check
venv\Scripts\python.exe scripts\project_memory.py check
```

If a check cannot run, report the concrete reason.

## Commit Rule

After a completed change:

1. Stage only the relevant source/test/docs/memory files.
2. Validate staged files:
   ```powershell
   venv\Scripts\python.exe scripts\project_memory.py check --staged
   venv\Scripts\python.exe scripts\check_commit_hygiene.py --staged
   ```
3. Commit with a short imperative message.
4. Report the commit hash and whether the branch is ahead of origin.

Push only when the user asks to push or explicitly asks to keep the remote in sync.

## Operational Defaults

- For daily pipeline questions, verify `status/daily_run_state.json`, `logs/scheduled/daily_pipeline.log`, lock files, and live processes before launching anything.
- For long-running pipeline work, verify progress from state/log artifacts before claiming success.
- Keep Grays hammer-bid logic separate from retail resale curve evidence.
- Keep source commits separate from runtime CSV/artifact commits unless the user explicitly asks for an intentional data commit.
- Treat tracked runtime CSV churn as quiet by default. Run `scripts\git_runtime_quiet.ps1 -Mode quiet` during normal source work and do not report runtime CSV dirt unless the user asks for data status, an intentional data snapshot, or the CSV changes are directly relevant to the task. Use `-Mode unquiet` only when intentionally reviewing or committing data.
