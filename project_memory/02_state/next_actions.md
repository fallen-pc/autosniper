# Next Actions

1. Review the current VIC active opportunity before changing margin/buffer constants: after refreshing valuations under the VIC-local rules, only one current curve-covered active row remains buyable, a VIC Hyundai i30 `Conditional Flip`.
2. Use the updated AI Analysis page as the daily active-opportunity screen and judge it against real listings. The current UI is now good enough to use, but future tuning should be based on what is confusing during actual auction review, not on more speculative layout work.
3. Keep Toyota hatch evidence alignment stable across the Autotrader recent-market lane and the repaired sold/Grays lane, without silently turning that work into repricing.
4. Keep `project_memory/02_state/` current after each meaningful work slice.
5. Use the launcher bootstrap contract for every fresh AI task so new sessions start from repo memory instead of chat recall.
6. If a Toyota hatch or Corolla sedan repricing review is explicitly requested later, run it as its own task; the structural tag/duplicate cleanup is now separate from price changes, and the Corolla Ascent ZRE182R hatch plus ZRE152R/ZRE172R sedans currently stay accepted as-is.
7. Treat Corolla ZWE211R `2018/2019` Ascent Sport Hybrid evidence as a possible future anchor-extension review, not an automatic change to the locked-in `2020/2021/2022` V2 grid.
8. Treat Corolla ZWE219R `2025` pricing as a possible future repricing review because Autotrader sits below the saved grid; do not change it as part of tag/source-of-truth cleanup.
9. Treat Hyundai i30 `Active X`, `SE`, `Elite`, `Premium`, `Trophy`, `SR`, `SR Premium`, and `N Line` as separate curve candidates, not as fallback evidence for the GD or PD Active curves.
10. Keep Camry AXVH71R `Ascent Hybrid` and `Ascent Sport Hybrid` as separate saved lanes; review `2025` Ascent Hybrid and any later-year Ascent Sport Hybrid evidence as deliberate year-extension tasks, not automatic merges.
11. Treat the Camry ASV70R petrol curve as live-market built: private Carsales and Autotrader carry the evidence, while the current single Grays sold row is non-contributory for valuation.
12. Watch the next available scheduled hourly run only as a scheduler sanity check: it is acceptable to miss a run when the laptop is off/asleep, but the next run while awake/logged in should resume cleanly.
13. Keep the enabled daily task in place and monitor only for regressions, not basic completion. The 2026-04-21 retry proved the current daily path can finish, but it is slow and still depends on the laptop being awake, plugged in if needed, logged in, and holding a valid visible-browser Autotrader session.
14. Keep using the refreshed Autotrader storage state and visible-browser Autotrader path unless headless mode is separately repaired; headless still should not be assumed stable.
15. If a future daily run fails after expensive Grays work, resume from the failed stage deliberately instead of rerunning the whole pipeline and overwriting useful completed stages.
16. Validate the new app-level missed-daily catch-up path with a real scheduler miss when convenient, but treat it as hardening verification rather than missing functionality.
17. Before committing future CSV snapshots, run `scripts/readiness_smoke.py` and `scripts/governance_checks.py check`, and sanity-check broad active counts against `active_vehicle_links.csv` and `vehicle_state.csv`.
18. Treat `active_snapshots.csv` as current live monitoring state only; hourly URL-scoped runs should reflect the monitored AI Analysis scope, and old history should be read from the archive instead of restored into the live file.
19. Keep the tracked CSV/artifact footprint under deliberate control. If the sandbox keeps needing large generated files in Git, decide that explicitly; otherwise move more generated outputs out of tracked paths instead of accepting silent churn.
20. The next meaningful work is no longer fixing a page bug; it is deciding whether to extend curve coverage deliberately. The current restricted Corolla row is correctly excluded because it sits outside the saved `toyota_corolla_zre172r_sedan_auto_petrol` year and km bands, so any attempt to make AI Analysis show it should be treated as a curve-extension review rather than a pipeline or tagging repair.
21. Next milestone is production-readiness hardening away from scheduler setup for now: profit/valuation correctness first, then scheduler reliability and Autotrader headless/session stability when the user is ready.
22. The next coverage-expansion step after the new tag batch is curves, not more generic tag sprawl. Camry Altise `ASV50R`, Mazda CX-5 Maxx Sport diesel `KE`, and Hyundai ix35 `SE LM` are now saved; next priority order is Hyundai Getz `TB` unless a stronger lane appears first.
