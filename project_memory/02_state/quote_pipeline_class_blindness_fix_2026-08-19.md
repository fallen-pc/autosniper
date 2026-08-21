# Fixed: the repair quote pipeline was class-blind — August 19, 2026

## Root cause of the 22,902-hit pricing gap

Traced why `repair_pricing_schedule.csv` covers almost nothing outside `small_hatch`
(confirmed earlier: 22 class-specific rows, 20 of them small_hatch). Two bugs in
`shared/repair_pricing_schedule.py`, both in the machinery that decides what still needs
a quote:

**`suggest_vehicle_class()`** defaulted every canonical except four explicit exceptions to
`"small_hatch"`. Every quote request this tool has ever drafted asked for a small-hatch price,
regardless of what vehicle class the gap was actually in.

**`needs_pricing()`** checked `canonical_defect` presence in the schedule only —
`priced = set(schedule_df["canonical_defect"])`. The instant ANY class got a price for a
canonical, that canonical vanished from "needs pricing" forever. `cosmetic_surface_damage`
disappeared from the list after its small_hatch quote came back, even though medium_suv (5,127
unpriced hits), small_sedan (2,922), ute (1,139) and van (538) were never asked about.

Confirmed against the real quote log: of 58 requests ever drafted, 45 were small_hatch, 11
generic (legitimately class-independent), only 2 medium_suv, and zero ute/van/small_sedan.

No scheduled/cron job for this exists in the repo (checked `scheduled_jobs.py`,
`.github/workflows`, all cron-like files) — `pages/19_REPAIR_PRICING.py` is a manual Streamlit
workflow. If something external ("codex") was scheduled outside this codebase, it isn't visible
from here.

## The fix

New class-aware core in `shared/repair_pricing_schedule.py`:

- **`REAL_VEHICLE_CLASSES`** = the 5 classes `infer_vehicle_class()` actually produces
  (small_hatch, small_sedan, medium_suv, ute, van) — distinct from `VEHICLE_CLASSES`, which
  also contains `large_suv` (never produced) and `generic` (not a body-class bucket).
- **`CLASS_VARYING_COST_MODELS = {"cosmetic_panel", "fixed_replacement"}`** — cost_models
  (from `repair_review_decisions.csv`) whose real cost differs by vehicle body class.
  Confirmed against the full 20,406-listing matrix: `glass` cost_model canonicals were already
  correctly covered end-to-end by one generic quote (real evidence, `window_tint_damage` shows
  `generic` status on every class), so glass is deliberately excluded from fanout.
- **`SINGLE_PRICE_CANONICALS`** = `{battery_issue, windscreen_damage, window_damage,
  window_tint_damage}` — an explicit override. `battery_issue`'s decision-file cost_model is
  `fixed_replacement` (would otherwise be class-varying), but an earlier version of this module
  had already special-cased it as a single generic price, and it already has a working generic
  quote on record. Kept that call rather than silently overturning it.
- **`missing_vehicle_classes_for(canonical, schedule_df, cost_models=, priority_order=)`** —
  the real fix. Class-varying canonicals need a row per class (a generic or single-class row
  does not count as covering the others); non-varying canonicals need exactly one row, under
  any class label.
- **`_class_priority_order()`** — ranks the 5 classes by real unpriced listing-hit volume from
  `CSV_data/model_audit/repair_pricing_matrix.csv`, falling back to a fixed order if that file
  doesn't exist yet. This is what makes `suggested_vehicle_class` point at the class that
  actually moves the needle instead of an arbitrary default.
- **`needs_pricing()`** rewritten on top of these. Adds `missing_vehicle_classes` and
  `missing_vehicle_classes_display` columns. `suggested_vehicle_class` is now the highest-impact
  still-missing class, not a hardcoded default.

## Verified against real production data

    needs_pricing() on the real candidates/schedule: 58 canonicals still need pricing
    cosmetic_surface_damage  -> suggested: medium_suv  (was: small_hatch)
    paint_damage             -> suggested: medium_suv  (was: small_hatch)
    seat_damage              -> suggested: medium_suv  (was: small_hatch)
    seat_issue               -> suggested: medium_suv  (was: small_hatch)
    interior_trim_damage     -> suggested: medium_suv  (was: small_hatch)
    battery_issue, windscreen_damage -> correctly absent (already fully priced)

`medium_suv` is the real top-impact class for these (5,127 hits for cosmetic_surface_damage
alone) — the old logic would have suggested small_hatch, which was already priced, on every one
of them.

## Second bug found and fixed in the same pass

`pages/19_REPAIR_PRICING.py`'s Quote Requests tab had its own, separate instance of the same
defect: `q_vehicle_class = st.selectbox("Vehicle class", VEHICLE_CLASSES, key="quote_vehicle_class")`
had no `index=` argument at all, so it always opened on `VEHICLE_CLASSES[0]` (`small_hatch`)
regardless of what `needs_pricing()` suggested — this is the literal control used to draft a new
quote request, so fixing the backend alone would not have fixed the actual send-a-quote workflow.
Now reads `suggested_vehicle_class` from the selected row, same pattern already used correctly
in the Needs Pricing tab.

## Tests

32 tests in `tests/test_repair_pricing_schedule.py` (12 new), covering: class-varying vs
non-varying classification, the SINGLE_PRICE_CANONICALS override, priority ordering from a
synthetic matrix fixture, the matrix-absent fallback, and `needs_pricing()` end-to-end keeping a
partially-priced canonical with its real remaining gap. Full suite: 1,002 passed, 1 xfailed.

Two of the new tests initially failed for a test-authoring reason, not a code reason: the shared
`_pricing_row()` test helper hardcodes `canonical_defect="panel_damage"`, and `needs_pricing()`
looks up cost_model from the real on-disk decisions file, so a fabricated canonical silently
resolved to "no cost_model on record" instead of exercising the class-varying path. Fixed by
using a real production canonical (`cosmetic_surface_damage`) in the two `needs_pricing()`
end-to-end tests, which also makes them a live regression check against the actual decisions
file rather than a synthetic-only fixture.

## Next (parts 2 and 3 of this pass)

1. Generate a fresh batch of quote-request drafts using the now-fixed `needs_pricing()`,
   targeting the top 20 missing (canonical, class) cells — 88% of the 22,902-hit gap.
2. Web research for interim evidence-based prices on the highest-impact cells, so decisions
   aren't blocked waiting on real supplier quotes to come back.
