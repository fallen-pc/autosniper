# Open Issues

- Profit-related terms and calculations may still drift across code and UI surfaces.
- Toyota Corolla `zre182r` hatch grouping has been split by trim, but the new base curves still need manual rebuild work so the old conflicting legacy branches are replaced with clean saved curves.
- `toyota_corolla_ascent_zre182r_hatch_auto_petrol` now resolves to about `24` recent-market Autotrader rows plus `1` sold Grays row, but the saved provisional curve still needs a sanity check against that evidence lane before it can be called complete.
- `toyota_corolla_ascent-sport_zre182r_hatch_auto_petrol` now resolves to about `33` recent-market Autotrader rows plus `4` sold Grays rows, and the current provisional Sport curve looks conservative against the active-market lane.
- The governed active CSVs remain Grays-dominated, so Toyota hatch active-market completeness should be judged from the tagged Autotrader evidence lane, not from `CSV_data/scrapers/active_vehicle_details.csv`.
- Curve Builder V2 expansion blockers are now better mapped; the current Toyota work is operational rebuilding, not silent legacy merging.
- Scraper and extractor surfaces remain high sensitivity and should not be reopened casually.
- Runtime memory enforcement still depends on using `scripts/start_ai_task.ps1` or an equivalent wrapper as the only front door into Codex/OpenClaw work for this repo.
