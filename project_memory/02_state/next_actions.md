# Next Actions

1. Map every place profit is computed, displayed, ranked, or calibrated.
2. Keep Toyota hatch evidence alignment stable across the Autotrader recent-market lane and the repaired sold/Grays lane, without silently turning that work into repricing.
3. Keep `project_memory/02_state/` current after each meaningful work slice.
4. Use the launcher bootstrap contract for every fresh AI task so new sessions start from repo memory instead of chat recall.
5. If a Toyota hatch repricing review is explicitly requested later, run it as its own task; otherwise reassess the next safest Toyota curve, with `toyota_corolla_ascent_petrol_auto_sedan_zre152r` the current leading candidate.
6. Re-run the hourly monitor after the scheduler fix and confirm it writes `output/health/scraper_health.json` plus a clean exit in `logs/scheduled/hourly_active_monitor.log`.
7. Refresh the Autotrader cookie/storage state, then run a one-page Autotrader smoke scrape before trusting the daily pipeline again.
8. After Autotrader is healthy, run a real daily pipeline smoke test and confirm the scheduled tasks stop returning `Last Result: 1`.
