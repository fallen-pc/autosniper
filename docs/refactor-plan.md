# AutoSniper Refactor Plan

## Goal
Improve architecture clarity, repo hygiene, and execution boundaries without rewriting the product or changing user-visible behavior.

## Non-goals
- No database migration in this refactor
- No Streamlit replacement
- No product feature rewrite
- No curve/governance logic redesign unless needed for structural cleanup

## Current structural assessment
The repo already has a workable spine:
- `shared/` contains much of the reusable logic
- `scripts/` contains most executable workflows
- `pages/` contains the Streamlit operator surface
- `CSV_data/` contains operational datasets
- `config/` contains governed configuration/reference data
- `tests/` covers several important domain modules

Main problems:
1. `shared/` is overloaded with domain logic, UI helpers, and operational utilities.
2. `scripts/` mixes pipeline jobs, governance runners, automation wrappers, repair/backfill jobs, and model/training tasks.
3. `CSV_data/` mixes governed assets with runtime materializations and generated outputs.
4. The repo root is too busy and the UI layer is still too close to storage/runtime details.

## Target structure

### Code layers
- `domain/` — business/domain logic (curves, canonical tagging, state machine, validation, pricing, governance primitives)
- `ui/` — Streamlit entrypoints, pages, navigation, UI-only helpers
- `jobs/` — scheduled or repeatable ingestion/materialization workflows
- `governance/` — integrity checks, contract enforcement, reporting runners
- `ops/` — operator/admin workflows and human-in-the-loop utilities
- `maintenance/` — backfills, repair jobs, migrations, cleanup scripts

### Data classes
- Governed assets — versioned, reviewed, tracked
- Runtime materializations — rebuildable operational outputs
- Audit/report outputs — generated, usually not source-of-truth
- Ephemeral local outputs — logs, temp files, caches
- Manual evidence/notes — selectively tracked

## Recommended phases

### Phase 1 — Repo hygiene and policy
- Add `docs/storage-policy.md`
- Add `docs/repo-structure.md`
- Tighten `.gitignore`
- Stop tracking obviously generated/high-churn outputs where safe

### Phase 2 — Split executable intent
Move `scripts/` contents into role-based folders with minimal logic changes:
- `jobs/`
- `governance/`
- `ops/`
- `maintenance/`

### Phase 3 — Rename `shared/` to `domain/`
Move clearly domain-oriented modules first. Leave ambiguous helpers for a second pass if needed.

### Phase 4 — Establish `ui/`
Move app entrypoints/pages/navigation into a clearer UI package. Keep root shims temporarily if convenient.

### Phase 5 — Centralize dataset path/loading logic
Create a single authority for dataset locations and loading/writing behavior.

### Phase 6 — Consolidate legacy/version drift
Remove V2/legacy duplication where one path is now canonical (especially curve builder surfaces).

## Exact first-pass move map

### Rename package
- `shared/` -> `domain/`

### UI moves
- `DASHBOARD.py` -> `ui/app.py` or keep as shim importing `ui.app`
- `app.py` -> `ui/app_shell.py` or merge into `ui/app.py`
- `status_app.py` -> `ui/status_app.py`
- `pages/` -> `ui/pages/`
- `shared/navigation.py` -> `ui/navigation.py`
- `shared/styling.py` -> `ui/styling.py`
- `shared/ui_helpers.py` -> `ui/helpers.py`
- `shared/styles.css` -> `ui/styles.css`
- `shared/filter_controls.py` -> `ui/filter_controls.py`
- `shared/global_filters.py` -> `ui/global_filters.py`

### Governance moves
- `scripts/governance_checks.py` -> `governance/run_checks.py`
- `scripts/check_commit_hygiene.py` -> `governance/check_commit_hygiene.py`
- `scripts/curve_coverage_report.py` -> `governance/curve_coverage_report.py`
- `scripts/curve_validator.py` -> `governance/curve_validator.py`
- `scripts/readiness_smoke.py` -> `governance/readiness_smoke.py`

### Jobs moves
- `scripts/extract_links.py` -> `jobs/extract_links.py`
- `scripts/extract_vehicle_details.py` -> `jobs/extract_vehicle_details.py`
- `scripts/update_bids.py` -> `jobs/update_bids.py`
- `scripts/update_master.py` -> `jobs/update_master.py`
- `scripts/pipeline_stages.py` -> `jobs/pipeline_stages.py`
- `scripts/build_restricted_datasets.py` -> `jobs/build_restricted_datasets.py`
- `scripts/normalize_listing_csvs.py` -> `jobs/normalize_listing_csvs.py`
- `scripts/normalize_conditions.py` -> `jobs/normalize_conditions.py`
- `scripts/rebuild_sold_dataset.py` -> `jobs/rebuild_sold_dataset.py`
- `scripts/scrape_bid_history.py` -> `jobs/scrape_bid_history.py`
- `scripts/scheduled_jobs.py` -> `jobs/scheduled_jobs.py`
- `scripts/run_grays_pipeline_loop.py` -> `jobs/run_grays_pipeline_loop.py`

### Ops moves
- `scripts/generate_curve_candidates.py` -> `ops/generate_curve_candidates.py`
- `scripts/process_curve_candidates.py` -> `ops/process_curve_candidates.py`
- `scripts/ai_listing_valuation.py` -> `ops/ai_listing_valuation.py`
- `scripts/ai_price_analysis.py` -> `ops/ai_price_analysis.py`
- `scripts/analyze_bid_history.py` -> `ops/analyze_bid_history.py`
- `scripts/render_curve_images.py` -> `ops/render_curve_images.py`
- `scripts/outcome_tracking.py` -> `ops/outcome_tracking.py`
- `scripts/prepare_sold_training_data.py` -> `ops/prepare_sold_training_data.py`
- `scripts/train_auction_price_correction.py` -> `ops/train_auction_price_correction.py`

### Maintenance moves
- `scripts/backfill_condition_notes.py` -> `maintenance/backfill_condition_notes.py`
- `scripts/backfill_legacy_sales.py` -> `maintenance/backfill_legacy_sales.py`
- `scripts/clean_sold_csv.py` -> `maintenance/clean_sold_csv.py`
- `scripts/enrich_sold_repairs.py` -> `maintenance/enrich_sold_repairs.py`
- PowerShell/CMD wrappers can either stay under `scripts/` temporarily or move to `ops/windows/`

## Module classification inside `shared/`

### Strong candidates for `domain/`
- `canonical_tagging.py`
- `comps_engine.py`
- `condition_normalizer.py`
- `csv_utils.py`
- `curve_builder_v2.py`
- `curve_groups_v2.py`
- `curve_versioning.py`
- `curves.py`
- `exclusions.py`
- `governance.py`
- `manual_curve_evidence.py`
- `parts_cost.py`
- `repair_features.py`
- `repair_pricing.py`
- `schema.py`
- `sold_cleaning.py`
- `state_machine.py`
- `validators.py`
- `top_buy.py`

### Likely UI package candidates
- `navigation.py`
- `filter_controls.py`
- `global_filters.py`
- `styling.py`
- `ui_helpers.py`
- `styles.css`

### Operational/infrastructure candidates (consider later split)
- `data_loader.py`
- `logging_utils.py`
- `ops_utils.py`
- `scraper_health.py`
- `telegram_alerts.py`
- `audit.py`
- `location_utils.py`

## Risk areas
- Import churn across `pages/`, `scripts/`, and `tests`
- Streamlit main-file assumptions (`DASHBOARD.py` at repo root)
- Git hooks/docs/CI path references pointing to `scripts/...`
- Windows automation wrappers hardcoding old paths
- Tests and notebooks/scratch scripts importing `shared.*`
- Data loader assumptions around `CSV_data/` location

## Validation checkpoints
After each phase:
- `pytest` (or at least targeted tests)
- `python -m compileall` over moved Python packages
- Governance smoke command still works
- Streamlit launches via the existing root entrypoint shim
- Hook/setup docs updated if paths changed

## First actual commit sequence
1. `docs: add refactor plan, storage policy, and repo structure docs`
2. `chore: tighten ignore rules and classify generated artifacts`
3. `refactor: split scripts into jobs, governance, ops, and maintenance`
4. `refactor: rename shared package to domain`
5. `refactor: move streamlit app into ui package with root shims`
6. `refactor: centralize dataset path and loader logic`
7. `refactor: consolidate curve builder legacy/v2 surfaces`

## Rollback strategy
- Keep each phase in a separate commit
- Preserve root entrypoint shims while moving UI files
- Avoid deleting legacy paths until imports and runtime references have been updated and validated
- Prefer move-only commits before any behavioral cleanup
