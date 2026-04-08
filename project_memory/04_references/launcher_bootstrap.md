# Launcher Bootstrap

The repo cannot force Codex or OpenClaw to preload memory by itself. The launcher must call the memory bootstrap command and abort on any non-zero exit code.

Recommended contract:

```powershell
python scripts/project_memory.py build-context --task-kind write --intent write --output tmp/project_context.json
```

Then the launcher should inject the JSON or the `session_context_markdown` field into the new task before asking the model to do work.

Minimum rule:

- if `build-context` fails, do not start the task
- if a task will edit code, use `--intent write`
- pick the narrowest task kind that matches the work: `write`, `valuation`, `curves`, `ui`, `scraper`, or `governance`
