# 2026-06-18 Hourly Active Materialization

- Fixed the hourly monitor path so `scripts/scheduled_jobs.py::run_hourly_monitor()` rematerializes master active/sold/referred views after scoped `update_bids(..., skip_master=True)` work.
- Root cause: hourly bid updates could write `Sold` or `Referred` statuses into `CSV_data/scrapers/active_vehicle_details.csv`, then health reporting ran before `scripts.update_master` rebuilt the active view.
- Verification after the old in-flight hourly process finished: live active CSV had `418` rows, `{'active': 418}` status mix, zero terminal status rows, zero terminal `vehicle_state.csv` overlap, zero active URLs missing from `active_vehicle_links.csv`, and `output/health/scraper_health.json` matched the live active count/status mix.
- Focused checks passed: scheduled-job regression tests, materialized-view/readiness tests, update-master snapshot tests, and `scripts/readiness_smoke.py`.
