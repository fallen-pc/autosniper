# Open Issues

- Profit-related terms and calculations may still drift across code and UI surfaces.
- Toyota Corolla `zre182r` hatch grouping has been split by trim, but the new base curves still need manual rebuild work so the old conflicting legacy branches are replaced with clean saved curves.
- `toyota_corolla_ascent_zre182r_hatch_auto_petrol` now has a manual/provisional shape, but the repo still shows `0` active Autotrader rows and only `1` sold Grays row for the mapped family, so completeness is not yet proven.
- `toyota_corolla_ascent-sport_zre182r_hatch_auto_petrol` still needs its own manual rebuild from genuine Ascent Sport evidence.
- Curve Builder V2 expansion blockers are now better mapped; the current Toyota work is operational rebuilding, not silent legacy merging.
- Scraper and extractor surfaces remain high sensitivity and should not be reopened casually.
- Runtime memory enforcement still depends on using `scripts/start_ai_task.ps1` or an equivalent wrapper as the only front door into Codex/OpenClaw work for this repo.
