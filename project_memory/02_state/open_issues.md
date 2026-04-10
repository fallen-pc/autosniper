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
- Daily and hourly Windows scheduled tasks are currently disabled on purpose, so unattended overnight runs are paused until the next active pipeline session.
- The hourly monitor now runs far enough to process live Grays URLs, but it is heavy enough that manual smoke tests can run for several minutes.
- Autotrader now has a refreshed storage state and succeeds in visible-browser (`playwright-headful`) smoke tests, but headless mode still returns `403`.
- The daily pipeline is still not proven healthy end-to-end with the refreshed Autotrader session because the scheduled tasks were paused before a full unattended daily run was completed.
- The Windows scheduled tasks are still registered as `Interactive only`, so they depend on the user session being logged in.
