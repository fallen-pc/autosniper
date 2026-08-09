# Missed Opportunities comps-count replay gate - 2026-07-01

Missed Opportunities now enriches each historical sold replay row with live-style
sold comparable count and median context before calling
`shared.missed_opportunities.compute_decision_metrics()`.

The replay builds the same preferred exact-year, then curve-tag group, comps
lookup shape used by AI Analysis and passes `historical_match_count`,
`historical_price_median`, `comps_count`, and `comps_median` into the shared
decision policy. The current sold row is excluded from its own comparable set by
URL before count/median are returned, with a fallback from exact-year to group
stats if the exact-year bucket only contained that row. This prevents historical
rows with fewer than 3 sold comps from remaining `Buy` misses when live AI
Analysis would classify them as `Watch`.

Current local replay impact after repair/WOVR/future-date exclusions:

- Old replay: 38 `Buy` misses, $240,047 projected missed profit.
- Patched replay: 32 `Buy` misses, $194,716 projected missed profit.
- 6 low-comps rows moved from `Buy` to `Watch`, removing $45,331 from current
  missed-profit totals.
