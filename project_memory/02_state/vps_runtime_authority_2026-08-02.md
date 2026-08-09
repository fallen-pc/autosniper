# VPS Runtime Authority - 2026-08-02

## Current authority

- The DigitalOcean VPS at `/opt/autosniper` is the live AutoSniper production runtime.
- It owns systemd scheduler state, scraper output, generated CSV data, logs, browser sessions, health reports, and Streamlit runtime state.
- The laptop checkout is for development. Its Windows scheduled tasks should remain disabled while the VPS is production, and its runtime CSVs may be stale snapshots.

## Audit rule

For any question about whether scrapers are running, listings are fresh, scheduled jobs succeeded, or AI valuations are current:

1. Inspect the VPS read-only Scraper Operations page or use read-only SSH checks.
2. Check `autosniper-daily.timer`, `autosniper-hourly.timer`, `status/daily_run_state.json`, `output/health/scraper_health.json`, and the relevant VPS-owned CSV timestamps.
3. Do not use disabled laptop tasks or laptop CSV modification times as production evidence.
4. Keep a single runtime writer. Do not enable laptop production jobs while the VPS timers are active.

## Live verification on 2026-08-02

- `autosniper.service` was active and enabled.
- Daily and hourly systemd timers were enabled.
- The latest daily run completed successfully with local coverage date `2026-08-02`.
- The latest hourly monitor completed successfully at `2026-08-02T06:20:39Z`.
- VPS health reported fresh active, sold, and valuation datasets; only the exclusion log was marked stale/partial.
- Unattended VPS Autotrader had already been proven with Linux Chromium under `xvfb-run`.

Current deployment workflow: `docs/vps_sync_workflow.md`.
