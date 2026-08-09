# Sandbox Workflow Validation Checklist

Purpose: verify useful operator flows in the sandbox now that the app is broadly launchable.

Keep this lightweight. Record what works, what fails, and whether the blocker is:
- code bug
- missing dependency
- missing dataset
- missing browser/system library
- missing service/config/credentials

## Validation rules
- Run from the sandbox repo only
- Use the Linux-side venv from the WSL runbook
- Do not treat generated CSV churn as source changes to commit
- Prefer short notes over exhaustive narration

## Pass 1: Page load sanity
Mark each as:
- loads cleanly
- loads with warnings only
- loads but feature blocked
- fails to load

Suggested pages to check:
- `DASHBOARD.py`
- `pages/6_AI_ANALYSIS.py`
- `pages/17_MODEL_PROOF.py`
- `pages/05_HEALTH.py`
- `pages/15_CURVE_BUILDER_V2.py`
- scraper/operator pages only as needed for actual sandbox bring-up validation

## Pass 2: Useful operator flows
### Curve/operator flow
- Open curve builder
- Confirm page renders fully
- Confirm base interactions do not immediately error
- Note any dataset/service blockers separately from code bugs

### Buying flow
- Use AI Analysis as the daily decision screen
- Confirm Dashboard cards are a condensed projection of the same active scope
- Use Active Inventory only for scraper coverage, raw status, and bid-data checks

### Normalisation governance
- Review exceptions and listing detail without exposing a direct rule-writing editor
- Change normalisation or allowed-variant rules through the governed source/test workflow

### Master database flow
- Open master database page
- Trigger the relevant action if safe
- Confirm subprocess uses the active interpreter rather than relying on bare `python`

### Scraper/operator flow
Only if intentionally validating runtime compatibility in sandbox.
- Confirm link extraction page launches commands under the active interpreter
- Confirm detail extraction page launches commands under the active interpreter
- Confirm scraper page launches commands under the active interpreter
- Distinguish browser/dependency failures from code defects

## Classification template
For each issue found, note:
- page / flow
- exact error
- classification: code bug / dependency / dataset / browser-lib / service-config
- whether it is safe to fix mechanically
- whether it should be deferred

## Current known examples
- `python: not found` shell-outs -> mechanical code/runtime fix
- missing `streamlit`, `bs4`, `playwright`, `dotenv`, `openai`, `matplotlib`, `scikit-learn` -> dependency issue
- missing browser libs for Playwright -> OS/browser dependency issue
- missing CSV inputs -> dataset/runtime-state issue

## Exit condition
Stop when one of these is true:
- the main pages and the most useful flows are usable enough for normal sandbox work
- remaining failures are clearly external/dependency/data issues rather than page-load code bugs
- further work would become broad cleanup rather than targeted validation
