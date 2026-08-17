# Cosmetic pricing gaps no longer refuse a decision — August 16, 2026

## The bug

`repair_pricing_schedule.csv` holds **28 rows across two vehicle classes** — `generic` and
`small_hatch`. The `generic` class covers only six things (battery, keys, tyres, window, tint,
windscreen). **Every cosmetic and interior canonical exists only under `small_hatch`.**

So a scratch on any SUV, ute, van or sedan found no cost band, was flagged
`pricing_class_uncertain`, and hit:

    elif repair_assessment.pricing_class_uncertain and action_label != "Avoid":
        computed_verdict = "Review (repair pricing evidence)"

Replayed over 989 historical sold rows, that single condition turned **65 winnable cars into
Review**. Every one was profitable against independently observed retail exits, and **38 had
sold BELOW the system's own max bid**. The blocking canonicals were entirely cosmetic:

    65  cosmetic_surface_damage      18  seat_damage
    15  paint_damage                  9  interior_trim_damage
     4  seat_issue                    1  each: carpet_torn, generic_damage,
                                         paint_surface_issue, panel_alignment_damage

The system was refusing to bid on cheap, profitable cars because it had no class-specific price
for a $450 scratch.

## The fix

`shared/repair_pricing.pricing_uncertainty_blocks_decision(assessment)` — unpriceable
**mechanical** items still force Review; unpriceable **cosmetics** no longer do. An assessment
flagged uncertain with no named cause stays cautious.

Deliberately placed in `shared/repair_pricing.py` and called from BOTH
`scripts/ai_listing_valuation.py` and `shared/missed_opportunities.py`, so the live path and the
replay cannot drift — that divergence class of bug was found twice earlier in this project.

The uncertainty is still surfaced: `repair_pricing_class_uncertain`,
`repair_pricing_incompatible_canonicals` and the `REPAIR_PRICING_CLASS_UNCERTAIN` risk flag are
unchanged. Only the refusal to decide was removed.

## Measured effect (989 replayed rows)

| | before | after |
|---|---|---|
| Buy | 20 | **79** |
| Review | 65 | 6 |
| Avoid | 904 | 904 |
| false positives | 0 | **0** |
| precision | 100.0% | **100.0%** |
| recall | 3.2% | **12.5%** |

Nearly 4x the recall with **zero** new false positives. A counterfactual with the gate removed
entirely scored 77 Buys, so restricting the relaxation to cosmetics costs almost nothing and
keeps the mechanical protection.

## What this does NOT fix

555 false negatives remain, from two constraints this change does not touch:

* **594 rows have `max_bid = 0`.** Relaxing the warning-light hard-avoids was separately tested
  and converted **zero** of them to Buy (see `repair_gate_counterfactual_2026-08-16.md`).
* **287 rows would have been outbid** — `max_bid > 0` but at or below the sold price.
  `curve_resale / retail_estimate` has median 0.85 and the curve sits below observed retail on
  83% of rows. That gap may simply be the asking-to-sale discount; separating the two needs
  realised sale prices, which do not exist yet.

Precision of 100% is also weakly informative here: the profitability bar is $1,500 while the
median simulated profit on new Buys was ~$5,400, so almost anything bought clears it.

## Still worth doing

Adding `generic` rows to `repair_pricing_schedule.csv` for the nine cosmetic canonicals. The fix
above stops the gap from blocking decisions, but the costs are still coming from fallbacks rather
than evidenced prices. Schedule reference (`small_hatch`): cosmetic_surface_damage $450,
paint_damage $800, carpet_torn $900, seat_damage $500, panel_alignment_damage $450,
generic_damage $500, paint_surface_issue $350, interior_trim_damage $250, seat_issue $250.

Also unresolved: **`vehicle_class` was blank on 34 of the 65 rows** — `infer_vehicle_class` is not
resolving those body types, which breaks class-specific pricing everywhere, not just here.

## Note on the repair review queue

The earlier recommendation to work the 292-item queue was wrong for this problem. Only 6 of the
65 blocked rows were `Review (unresolved repairs)`; the other 59 were `pricing_class_uncertain`,
which the queue does not touch.

## Tests

983 pass. Two existing tests asserted the old behaviour on a `cosmetic_surface_damage` /
`medium_suv` / "Front guard scratched." case and were updated to the new intent, with mechanical
and mixed-gap companions added so the protective half stays covered.
