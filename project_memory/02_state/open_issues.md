# Open Issues

- Profit-related terms and calculations may still drift across code and UI surfaces.
- Toyota Corolla hatch `toyota_corolla_zre182r_hatch_auto_petrol` is blocked because its two mapped legacy `zre18x` source curves disagree on overlapping 2018 anchor/km cells.
- A clean decision is still needed on the Toyota hatch family: rebuild from fresh evidence, choose one legacy shape, or explicitly retire one branch.
- Curve Builder V2 expansion blockers are now better mapped; the known live blocker is conflicting legacy fallback data for at least the Toyota hatch family.
- Scraper and extractor surfaces remain high sensitivity and should not be reopened casually.
- Runtime memory enforcement still depends on using `scripts/start_ai_task.ps1` or an equivalent wrapper as the only front door into Codex/OpenClaw work for this repo.
