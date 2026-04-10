# Current Status

- The sandbox is broadly runnable and documented enough for real product work.
- The repo now has an enforced project-memory system with manifest loading, generated machine rules, protected layers, and a task bootstrap CLI.
- Commit hygiene now enforces that meaningful code/config/UI/governance changes should carry a matching `project_memory/02_state/` update in the same commit unless an intentional exception is declared.
- Existing root memory files remain in place only as compatibility summaries during the rollout.
- Current product priorities are:
  - verify profit determination accuracy across producer, ranking, display, and calibration surfaces
  - identify what blocks adding more curves safely in Curve Builder V2
- Toyota Corolla `zre182r` hatch mapping is now split by trim at the base-curve level so `ascent` and `ascent-sport` no longer pretend to be one shared curve family.
- Curve Builder V2 now blocks silent legacy fallback merges when mapped legacy rows disagree on the same anchor-year and km-bucket cell.
- `toyota_corolla_ascent_zre182r_hatch_auto_petrol` and `toyota_corolla_ascent-sport_zre182r_hatch_auto_petrol` now both have manual/provisional curves from Carsales-style market evidence, but neither is complete yet because active Autotrader alignment is still missing in the repo.
