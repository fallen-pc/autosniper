# Launcher Bootstrap

The repo cannot force Codex or OpenClaw to preload memory by itself. The launcher must call the memory bootstrap command and abort on any non-zero exit code.

Recommended contract:

```powershell
.\scripts\start_ai_task.ps1 -TaskKind write -Intent write -OutputPath tmp/project_context.json -LauncherCommand <your-launcher> <args...>
```

The wrapper script:

- runs `python scripts/project_memory.py build-context ...`
- aborts if bootstrap fails
- writes the context bundle to disk
- exports `AUTOSNIPER_PROJECT_CONTEXT_PATH`
- writes `session_context_markdown` to a sidecar markdown file
- exports `AUTOSNIPER_PROJECT_CONTEXT_MARKDOWN_PATH`
- writes a combined startup prompt to `tmp/session_start_prompt.md`
- exports `AUTOSNIPER_PROJECT_START_PROMPT_PATH`
- exports `AUTOSNIPER_PROJECT_CONTEXT_MARKDOWN` only when the markdown is small enough to fit safely in an env var
- exports `AUTOSNIPER_PROJECT_TASK_KIND` and `AUTOSNIPER_PROJECT_INTENT`

Then the downstream launcher should inject the JSON or the `session_context_markdown` field into the new task before asking the model to do work.

Minimum rule:

- if bootstrap fails, do not start the task
- if a task will edit code, use `--intent write`
- pick the narrowest task kind that matches the work: `write`, `valuation`, `curves`, `ui`, `scraper`, or `governance`
- do not launch Codex/OpenClaw for this repo by hand if you want memory enforcement to mean anything

Examples:

```powershell
.\scripts\start_ai_task.ps1 -TaskKind curves -Intent write -NoLaunch
```

```powershell
.\scripts\start_ai_task.ps1 -TaskKind valuation -Intent write -LauncherCommand python some_launcher.py
```

```powershell
.\scripts\start_ai_task.ps1 -TaskKind curves -Intent write -CopyPrompt -LaunchCodex -NoLaunch
```
