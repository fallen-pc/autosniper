# Next Actions

1. Map every place profit is computed, displayed, ranked, or calibrated.
2. Keep Toyota hatch evidence alignment stable across the Autotrader recent-market lane and the repaired sold/Grays lane, without silently turning that work into repricing.
3. Keep `project_memory/02_state/` current after each meaningful work slice.
4. Use the launcher bootstrap contract for every fresh AI task so new sessions start from repo memory instead of chat recall.
5. If a Toyota hatch repricing review is explicitly requested later, run it as its own task; otherwise reassess the next safest Toyota curve, with `toyota_corolla_ascent_petrol_auto_sedan_zre152r` the current leading candidate.
6. Re-enable the hourly and daily Windows scheduled tasks only when ready to let the repo move again.
7. When resuming pipeline work, start with a one-page Autotrader smoke scrape using the refreshed storage state and `--playwright-headful --playwright-browser chrome`.
8. After that passes, run a real hourly monitor test and confirm it writes `output/health/scraper_health.json` plus a clean exit in `logs/scheduled/hourly_active_monitor.log`.
9. Only then re-enable unattended daily automation and verify a full daily pipeline run completes successfully.
