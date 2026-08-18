# Repair pricing coverage matrix + vehicle class fix — August 16, 2026

## Item 1 — the matrix

`scripts/build_repair_pricing_matrix.py` emits the **full cross product**: every canonical that
needs a per-class price against every vehicle class, whether or not that combination has been
seen yet. A canonical observed only on a small_hatch today still needs a price for every class,
or the first ute showing it falls through to a guess and blocks the decision.

Canonicals are filtered to those whose review decision implies a real cost — `cosmetic_panel`,
`fixed_replacement`, `glass`. Items decided `no_cost` (boilerplate) or `hard_avoid` (flat bucket)
never consult the schedule and are excluded.

Cells are ranked by how often they actually occur in listings, so pricing effort goes where it
changes decisions rather than alphabetically.

    58 canonicals x 5 classes = 290 cells

    MISSING   252 cells (86.9%)
    generic    20 cells
    priced     18 cells

    of the 252 unpriced: 51 already occur in listings, 201 not yet seen

Output: `CSV_data/model_audit/repair_pricing_matrix.csv` — fill `schedule_value` per row, then
load into `repair_pricing_schedule.csv`. The `small_hatch_reference` column carries the existing
value as a starting point, though a ute panel is not a hatch panel.

## Item 2 — vehicle class

`infer_vehicle_class` returned "" for **9 body labels covering 7,619 sold listings**, dominated by
`wagon` / `Wagon` at 7,566.

`wagon` now maps to **medium_suv**. Of those 7,566 listings the top twenty nameplates are Land
Rover, Territory, Captiva, CX-5, Mercedes, Forester, Grand Cherokee, X5, X-Trail, LandCruiser,
RAV4, Outback, Tiguan, Pathfinder, Outlander, ix35, Kluger, CR-V, CX-9 and Tucson — **not one
traditional station wagon**.

Also added: `extra cab`, `king cab`, `space cab`, `crew cab`, bare `cab`, `utility`, `truck` ->
ute; `motor home` -> van; `cabriolet` / `roadster` -> small_sedan.

Ordering matters and is now explicit in the function:

* `cabriolet` resolves **before** the ute tokens, or the bare `cab` check swallows it
* utes resolve **before** SUV tokens, so a `dual cab 4x4` is a ute not an SUV

### Effect

Listing-hits with no vehicle class at all: **1,876 -> 1**.

`medium_suv` had never appeared in the coverage matrix despite SUVs being a large share of the
market, because they were all labelled `wagon` and stranded. It now leads the priority list:

    984  cosmetic_surface_damage  medium_suv
    623  cosmetic_surface_damage  small_sedan
    261  cosmetic_surface_damage  ute
    233  paint_damage             medium_suv
    202  seat_issue               medium_suv
    180  seat_damage              medium_suv

The pricing priority order is only trustworthy now that this is fixed — which is why it had to
come before the pricing work.

## Risk

Low. With no schedule row for a class, `_effective_cost_band` already fell through
exact -> generic -> fallback, and an unresolved class took the same path. So the cost outcome is
unchanged today; what changes is that the class is now recorded, making the matrix accurate and
letting future per-class prices actually apply.

Replay is unchanged at Buy 79 / recall 12.5% / precision 100%, as expected.

## Tests

990 pass. One pre-existing test asserted `vehicle_class_for_listing({"body_type": "Wagon"}) == ""`
— the behaviour deliberately changed — and was updated. Explicit `vehicle_class` override still
wins over inference, which that test also covers.

## Next

Item 3 — the 594 rows with `max_bid = 0`. Still unexplained: relaxing the warning-light
hard-avoids converted zero of them, so the cause is elsewhere.

Item 4 — the 287 outbid rows, where curve resale runs at a median 0.85 of observed retail. Needs
realised sale prices to separate genuine conservatism from the asking-to-sale gap.
