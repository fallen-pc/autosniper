# PR Slicing And Artifact Hygiene

## Goal
- Keep each commit reviewable and low-risk.
- Avoid mixing source changes with generated CSV/binary artifacts.

## Enable Hook
Run once per clone:

```powershell
.\scripts\setup_git_hooks.ps1
```

This sets `core.hooksPath=.githooks` and activates `pre-commit`.

## What The Hook Enforces
- Blocks mixed commits that include both source files and artifact files.
- Blocks oversized staged files (default `> 1,000,000` bytes).
- Blocks very large commit slices (default `> 80` files).

Artifact paths include:
- `CSV_data/`
- `artifacts/`
- `autotrader_isolated/output/`
- `catboost_info/`
- `curves/images/`
- `logs/`
- `output/`

## Recommended Commit Flow
1. Stage source-only changes and commit.
2. Stage data/artifact updates and commit separately (only when needed).
3. Prefer one purpose per commit.

## Optional Overrides (Use Sparingly)
- `AUTOSNIPER_ALLOW_MIXED_COMMIT=1`
- `AUTOSNIPER_MAX_COMMIT_FILES=80`
- `AUTOSNIPER_MAX_FILE_BYTES=1000000`

Example one-off override:

```powershell
$env:AUTOSNIPER_ALLOW_MIXED_COMMIT="1"
git commit -m "intentional mixed commit"
Remove-Item Env:AUTOSNIPER_ALLOW_MIXED_COMMIT
```
