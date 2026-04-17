# Next Actions

1. Map every place profit is computed, displayed, ranked, or calibrated.
2. Keep Toyota hatch evidence alignment stable across the Autotrader recent-market lane and the repaired sold/Grays lane, without silently turning that work into repricing.
3. Keep `project_memory/02_state/` current after each meaningful work slice.
4. Use the launcher bootstrap contract for every fresh AI task so new sessions start from repo memory instead of chat recall.
5. If a Toyota hatch or Corolla sedan repricing review is explicitly requested later, run it as its own task; the structural tag/duplicate cleanup is now separate from price changes, and the Corolla Ascent ZRE182R hatch plus ZRE152R/ZRE172R sedans currently stay accepted as-is.
6. Treat Corolla ZWE211R `2018/2019` Ascent Sport Hybrid evidence as a possible future anchor-extension review, not an automatic change to the locked-in `2020/2021/2022` V2 grid.
7. Treat Corolla ZWE219R `2025` pricing as a possible future repricing review because Autotrader sits below the saved grid; do not change it as part of tag/source-of-truth cleanup.
8. Treat Hyundai i30 `Active X`, `SE`, `Elite`, `Premium`, `Trophy`, `SR`, `SR Premium`, and `N Line` as separate curve candidates, not as fallback evidence for the GD or PD Active curves.
9. Keep Camry AXVH71R `Ascent Hybrid` and `Ascent Sport Hybrid` as separate saved lanes; review `2025` Ascent Hybrid and any later-year Ascent Sport Hybrid evidence as deliberate year-extension tasks, not automatic merges.
10. Treat the Camry ASV70R petrol curve as live-market built: private Carsales and Autotrader carry the evidence, while the current single Grays sold row is non-contributory for valuation.
11. Watch the next available scheduled hourly run only as a scheduler sanity check: it is acceptable to miss a run when the laptop is off/asleep, but the next run while awake/logged in should resume cleanly.
12. Keep daily disabled until a full daily smoke test is run with the refreshed Autotrader session.
13. When running that daily smoke test, use the refreshed storage state and keep the visible-browser Autotrader path in mind.
14. Only after a successful daily smoke test should unattended daily automation be re-enabled.
15. Before retrying daily, consider adding a safer daily smoke mode or a resume/limit path so the test does not need to churn through the full Grays update set in one fragile run.
16. Before committing future CSV snapshots, run `scripts/readiness_smoke.py` and `scripts/governance_checks.py check`, and sanity-check broad active counts against `active_vehicle_links.csv` and `vehicle_state.csv`.
17. Treat `active_snapshots.csv` as current live monitoring state only; hourly URL-scoped runs should reflect the monitored AI Analysis scope, and old history should be read from the archive instead of restored into the live file.
