# Repo Structure

## Intended layout

### Root
Keep the repo root minimal:
- top-level readme/config files
- temporary compatibility entrypoints only
- no new operational scratch files

### `domain/` (currently `shared/`)
Business/domain logic that should work without Streamlit:
- curves
- canonical tagging
- state machine
- validators
- pricing/comps
- governance primitives
- schemas

### `ui/`
Streamlit app surface:
- app entrypoint
- pages
- navigation
- styling
- UI helpers

### `jobs/`
Repeatable pipeline/materialization workflows:
- scrape links/details
- refresh bids
- rebuild datasets
- scheduled loops

### `governance/`
Integrity and review workflows:
- schema checks
- curve validation
- coverage reports
- readiness smoke checks
- commit hygiene checks

### `ops/`
Operator workflows and human-in-the-loop tools:
- curve candidate generation/processing
- AI valuation workflows
- reporting helpers
- training/evaluation helpers if still operator-facing

### `maintenance/`
One-off or occasional maintenance:
- backfills
- cleanup/migrations
- historical repair jobs

### `config/`
Governed configuration and reference tables.

### `data/` / current `CSV_data/`
Operational datasets, separated by governance level and lifecycle.

### `tests/`
Tests grouped around domain and workflow behavior.

## Rules for new code
- Do not add new reusable business logic under `pages/`.
- Do not add new mixed-purpose helpers under `shared/`; choose `domain/`, `ui/`, or an execution folder.
- Do not add new one-off scripts to the repo root.
- Prefer lowercase snake_case source filenames.
- Avoid `copy`, `backup`, `old`, `temp`, `final`, or `v2` in active-source filenames unless there is an explicit migration plan.

## Transitional compatibility
During the refactor:
- root `DASHBOARD.py` may remain as a shim
- old import paths may temporarily coexist where needed
- Windows wrappers may lag behind Python module moves for one phase

The goal is not instant purity; it is safer boundaries with minimal breakage.
