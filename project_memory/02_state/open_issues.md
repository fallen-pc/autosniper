# Open Issues

- Profit-related terms and calculations may still drift across code and UI surfaces.
- Toyota Corolla `zre182r` hatch grouping has been split by trim, but the new base curves still need manual rebuild work so the old conflicting legacy branches are replaced with clean saved curves.
- `toyota_corolla_ascent_zre182r_hatch_auto_petrol` now resolves to about `24` recent-market Autotrader rows plus `6` sold Grays rows.
- `toyota_corolla_ascent-sport_zre182r_hatch_auto_petrol` now resolves to about `33` recent-market Autotrader rows plus `10` sold Grays rows.
- The governed active CSVs remain Grays-dominated, so Toyota hatch active-market completeness should be judged from the tagged Autotrader evidence lane, not from `CSV_data/scrapers/active_vehicle_details.csv`.
- Any later Toyota hatch repricing review must stay separate from the tag-alignment task that fixed the evidence lanes.
- Curve Builder V2 expansion blockers are now better mapped; the current Toyota work is operational rebuilding, not silent legacy merging.
- Scraper and extractor surfaces remain high sensitivity and should not be reopened casually.
- Runtime memory enforcement still depends on using `scripts/start_ai_task.ps1` or an equivalent wrapper as the only front door into Codex/OpenClaw work for this repo.
- The hourly monitor should remain scoped to AI Analysis current viable listings, not the broad `508`-row active Grays working file.
- Occasional hourly Task Scheduler misses are acceptable when the laptop is off/asleep or the interactive session refuses the run; repeated failures while the machine is awake/logged in should be treated as a Windows scheduler configuration issue, not a scraper-pipeline rewrite.
- Hourly automation is back on; live runtime CSVs can still change locally, but hourly snapshot history should now be compacted out of the tracked current snapshot file.
- Autotrader now has a refreshed storage state and succeeds in visible-browser (`playwright-headful`) smoke tests, but headless mode still returns `403`.
- The daily pipeline has now completed end-to-end manually after a fix-and-resume flow, but it is still not proven as a clean unattended one-shot scheduled run.
- The Windows scheduled tasks are still registered as `Interactive only`, so they depend on the user session being logged in.
- Do not re-enable daily automation until one clean full daily run completes without manual resume, or until a deliberate daily resume/guard path is implemented and tested.
- If `active_vehicle_details.csv` collapses again, first compare URL overlap between `active_vehicle_links.csv`, `vehicle_static_details.csv`, and `vehicle_state.csv`; do not assume committing CSV churn fixes the issue.
- The project is currently a healthy sandbox, not a finished production buying system: daily end-to-end proof, Autotrader headless/session stability, Windows scheduler reliability, and profit/valuation correctness still need focused verification before trusting real-money decisions.
