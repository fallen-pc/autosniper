# Next Actions

1. Map every place profit is computed, displayed, ranked, or calibrated.
2. Keep Toyota hatch evidence alignment stable across the Autotrader recent-market lane and the repaired sold/Grays lane, without silently turning that work into repricing.
3. Keep `project_memory/02_state/` current after each meaningful work slice.
4. Use the launcher bootstrap contract for every fresh AI task so new sessions start from repo memory instead of chat recall.
5. If a Toyota hatch repricing review is explicitly requested later, run it as its own task; otherwise reassess the next safest Toyota curve, with `toyota_corolla_ascent_petrol_auto_sedan_zre152r` the current leading candidate.
6. Watch the next scheduled hourly run and confirm it also exits cleanly now that the task is re-enabled.
7. Keep daily disabled until a full daily smoke test is run with the refreshed Autotrader session.
8. When running that daily smoke test, use the refreshed storage state and keep the visible-browser Autotrader path in mind.
9. Only after a successful daily smoke test should unattended daily automation be re-enabled.
10. Before retrying daily, consider adding a safer daily smoke mode or a resume/limit path so the test does not need to churn through the full Grays update set in one fragile run.
