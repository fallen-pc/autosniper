# Current Status

- The sandbox is broadly runnable and documented enough for real product work.
- The repo now has an enforced project-memory system with manifest loading, generated machine rules, protected layers, and a task bootstrap CLI.
- Existing root memory files remain in place only as compatibility summaries during the rollout.
- Current product priorities are:
  - verify profit determination accuracy across producer, ranking, display, and calibration surfaces
  - identify what blocks adding more curves safely in Curve Builder V2
- Curve Builder V2's most immediate blocker is the Toyota Corolla hatch family: both legacy `zre18x` tags map into base curve `toyota_corolla_zre182r_hatch_auto_petrol`, but the legacy rows conflict.
- Curve Builder V2 now blocks silent legacy fallback merges when mapped legacy rows disagree on the same anchor-year and km-bucket cell.
- The only clearly saved manual V2-era curve work remains Hyundai GD and Mazda BL; Toyota hatch is not yet cleanly rebuilt.
