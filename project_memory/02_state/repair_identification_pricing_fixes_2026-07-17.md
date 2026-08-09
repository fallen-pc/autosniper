# Repair identification + pricing fixes (2026-07-17)

Audit of the Missed Opportunities repair path found four issues; all fixed in this change.

## 1. Mechanical hard-avoid gaps (shared/repair_pricing.py)

19 sold rows with clear mechanical-fault text were passing as cosmetic-only repairs and
inflating missed-profit KPIs (e.g. "engine issues" sold $10,000 assessed at $1,625;
"engine requires attention" sold $7,000 assessed at $3,750 cosmetic).

Added MECH_AVOID_PATTERNS for:
- engine/motor + requires/needs attention, issue(s), tick(ing)
- steering (excluding "steering wheel") + attention/noise/vibration/fault/issue
- driveline + attention/fault/issue/noise
- gearbox/transmission shudder
- coolant + leak/issue/fault/loss
- black/white/blue/excessive smoke, exhaust smoke, blowing smoke, smoke evident/visible/observed
- noise whilst/while/when driving

Full-dataset replay (sold_cars_restricted.csv, 2,623 rows): mechanical hard-avoids
770 -> 791, zero suspect mechanical lines remain in the non-avoid universe.

## 2. v2 dictionary pattern bugs (config/condition_dictionary_v2.yaml)

- warning_light pattern had no word boundary on (on|warning), so equipment lists
  ("dual frONt airbags", "park distance cONtrol") hard-avoided as mechanical.
  Now `\b(warning lights?|engine lights?|abs|airbag)\b.*\b(on|flashing|warning)\b`.
- structural pattern matched "a pillar trim" (interior plastic) as structural damage.
  Now `[abc][ -]?pillars?\b(?!\s+trim)`; real pillar dents still hard-avoid.
  Structural hard-avoids 13 -> 11 (the two pillar-trim rows released).

## 3. Schedule-driven repair costs (shared/repair_pricing.py)

`_schedule_cost_overrides()` now loads CSV_data/reports/repair_pricing_schedule.csv
(the curated source Page 19 maintains) and overrides V2_REPLACEMENT_COSTS:
- Quote-backed rows (repair_quote / parts_plus_labour / parts_supplier_price) are
  authoritative: control_damage $250 -> $900, seat_damage $250 -> $500,
  seat_issue $150 -> $250, sunroof $600 -> $800, battery $300 -> $250, hail $900 -> $1,000.
- Wrecker part-only rows only raise the hardcoded fitted-cost floor, never lower it
  (bumper stays $600 vs the $65 part-only price).
- Windscreen now $500 (schedule default) via `_windscreen_glass_cost()`; ADAS adds the
  $150 recalibration premium (WINDSCREEN_ADAS_PREMIUM); side window/tint use their own
  schedule rows ($350).
- Corrosion routed as body-shop work: $1,200 schedule quote, PANEL_REPLACE pill,
  with_replacement cap tier (was $300 cosmetic panel rate).

## 4. Hail cap exemption (shared/repair_pricing.py)

Hail/structural line cost (schedule default + panel_count x PANEL_RATE) now accumulates
in `uncapped_structural_cost` and bypasses HARD_CAPS (schedule high end for hail is
~$10k; the old $1,500 with_replacement cap flattened it to a $2,400 max bid deduction).
Hail panels no longer consume the capped cosmetic panel pool. Severe write-off-level
hail is generally WOVR and already excluded by the page's WOVR filter.

## Tests

tests/test_repair_pricing.py: +11 regression tests (mechanical phrases, feature-list
non-avoid, pillar trim split, schedule quote pricing, hail cap bypass, ADAS premium);
4 expectation updates for the new schedule-backed prices. All repair/missed-opportunity
suites pass (92 tests).

## Known open items

- PANEL_RATE ($300/panel) sits below the schedule's cosmetic_surface_damage quote
  ($450/panel single, $400/panel bundled) -- left unchanged, worth revisiting.
- Per-item low/high uncertainty bands (schedule low/high columns) still unused; global
  0.55/1.60 multipliers apply to the whole total.
