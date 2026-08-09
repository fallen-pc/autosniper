---
date: 2026-06-29
topic: Repair uncertainty band added to RepairAssessment
status: complete
---

`RepairAssessment` now carries `total_cost_low` and `total_cost_high` fields.
Multipliers: low=0.55, high=1.60 (derived from repair_pricing_schedule.csv percentiles).
`apply_repairs_to_max_bid()` deducts `total_cost_high` instead of `total_cost`,
giving a more conservative (safer) max bid when repair uncertainty is high.
`scripts/ai_listing_valuation.py` exposes `repair_estimate_low` and
`repair_estimate_high` in the result row for display.
