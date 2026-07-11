# Re-auction lifecycle handling

Implemented shared VIN + odometer lifecycle handling so repeat auction rows for the same vehicle are not treated as independent evidence everywhere.

- `shared/reauction.py` now centralizes VIN/odometer normalization, lifecycle collapse, re-auction summaries, active-listing re-auction context, and expected-finish adjustment.
- Missed Opportunities collapses repeated sold rows to the latest auction event after major-defect and WOVR exclusions, while retaining event count and first/last price movement fields.
- AI Analysis collapses sold comps before stats and passes active same-vehicle re-auction context into valuation. Expected auction finish is capped at the latest prior same-vehicle sale when that is lower than the normal estimate.
- Re-auction Monitor now uses the shared lifecycle helper so the grouping matches Missed Opportunities and AI Analysis.

Implementation check on current data: the repeated Hilux VIN `MR0KA3CD201195598` / `138896` km is retained once using the latest sale, with `reauction_event_count=2` and `reauction_price_delta=2100`.
