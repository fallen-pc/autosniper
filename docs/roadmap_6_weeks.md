# AutoSniper 6-Week Roadmap

Date range: March 16, 2026 to April 26, 2026

## Repo-Based Baseline
- Multi-page Streamlit app is already in place (`DASHBOARD.py`, `pages/`), including ops, health, AI analysis, model accuracy, pipeline controls, and Autotrader tools.
- Core Grays pipeline exists end-to-end: `extract_links.py` -> `extract_vehicle_details.py` -> `pipeline_stages.py` (`normalize`/`exclude`/`match`/`audit`) -> `update_bids.py` -> `update_master.py`.
- Data architecture is CSV-first with strict schemas and validators (`shared/schema.py`, `shared/validators.py`, `shared/data_loader.py`).
- AI valuation flow is implemented with risk adjustments and top-buy logic (`scripts/ai_listing_valuation.py`).
- Scheduled jobs and locking are implemented (`scripts/scheduled_jobs.py`, `scripts/run_daily.cmd`, `scripts/run_vic_12h.cmd`, `scripts/run_vic_hourly.cmd`).
- Test suite currently covers core valuation logic and selected pipeline rules (29 passing tests).
- Explicit in-repo TODO found: dashboard KPI/trend hooks still need to be finalized across `DASHBOARD.py` and `pages/`.

## Milestones
- M1 (end Week 2): Stable ingestion and update pipeline with clearer run health signals.
- M2 (end Week 4): Stronger data contracts and measurable valuation quality loop.
- M3 (end Week 6): Production-ready operator dashboard and release/handover package.

## Week-by-Week Plan

| Week | Goal | Deliverables | Key Dependencies / Risks |
|---|---|---|---|
| Week 1 (Mar 16-22) | Establish baseline and operational visibility | Pipeline runbook; stage-by-stage health/latency/error metrics in `status/`; weekly baseline report for row counts, failure reasons, and stale files | Dependency: stable access to Grays endpoints. Risk: current logs/CSV outputs are fragmented across scripts |
| Week 2 (Mar 23-29) | Harden scraping and scheduling reliability | Unified retry/backoff and timeout policy across link/detail/bid scrapers; lock + resume behavior cleanup; one-command smoke run for daily + VIC jobs | Dependency: Playwright/browser runtime + network stability. Risk: concurrent CSV writes can create race conditions |
| Week 3 (Mar 30-Apr 5) | Tighten data contracts and quality gates | Contract tests for major CSV schemas (`active`, `static`, `sold`, `referred`, `normalised`); validator coverage expansion; exclusion and canonical reason distribution dashboard | Dependency: stable schema ownership. Risk: source-site HTML changes causing parse drift |
| Week 4 (Apr 6-12) | Improve valuation quality and auditability | Backtest job producing weekly metrics into `CSV_data/model_audit/`; decision trace fields for AI outputs; threshold tuning for verdict confidence and no-edge flags | Dependency: sufficient settled sold data. Risk: model drift and heuristic overfitting |
| Week 5 (Apr 13-19) | Finalize production KPI dashboard view | Finalize KPI/trend definitions in `DASHBOARD.py`; wire drill-down actions into existing pages (`6_AI_ANALYSIS`, `12_GRAYS_PIPELINE`, `8_MODEL_ACCURACY`); align metric definitions in shared helpers | Dependency: agreed KPI definitions. Risk: UI inconsistency across legacy/new pages |
| Week 6 (Apr 20-26) | Release hardening and handover | Release checklist; rollback and data-recovery procedure for `CSV_data` bundle sync; operator SOP for daily/12h/hourly jobs; post-release monitoring and ownership matrix | Dependency: environment secrets (`OPENAI_API_KEY`, Telegram, data bundle URLs). Risk: production incidents without clear on-call playbook |

## Dependencies
- External sites and anti-bot constraints: Grays availability + Autotrader cookie/storage-state requirements.
- Runtime/environment: Python venv, Playwright browsers, Streamlit runtime, Windows task runners (`.cmd` + PowerShell).
- Secrets and integrations: `OPENAI_API_KEY`, optional Telegram tokens, optional remote data bundle URLs/tokens.
- Data continuity: `CSV_data` integrity and access to historical sold/referred snapshots for audit and backtesting.

## Risks and Mitigations
- CSV race conditions and partial writes.
- Mitigation: keep atomic writes everywhere, enforce single-writer locks, add stage-level conflict detection.
- Scraper breakage from HTML/layout changes.
- Mitigation: parser contract tests on fixture HTML + fallback selectors + alert when parse coverage drops.
- Status misclassification (`active`/`sold`/`referred`) due heuristic ambiguity.
- Mitigation: explicit status confidence flags and manual exception queue in ops pages.
- KPI drift between dashboards and pipeline outputs.
- Mitigation: single metric-definition module and weekly validation against source CSVs.
- Limited test coverage for orchestration paths.
- Mitigation: add integration smoke tests for the full pipeline and scheduled job variants.
