# Hyundai Curve Decisions

## i30 GD Active Hatch

Base curve:
- `hyundai_i30_gd_hatch_auto_petrol`

Current working interpretation:
- body: `hatch`
- transmission: `auto`
- fuel: `petrol`
- intended market slice: exact `Active` GD hatch retail market
- anchor years for current rebuild: `2012`, `2014`, `2016`
- `2013` and `2015` are expected to interpolate between those anchors

Included trims for the current GD pass:
- `Active`

Excluded trims for the current GD pass:
- `Active X`
- `Elite`
- `Premium`
- `Trophy`
- `SE`
- `SR`
- `SR Premium`

Why these exclusions exist:
- `Elite`, `Premium`, and `Trophy` are separate trim/value lanes and must not be silently mixed into an `Active` curve.
- `Active X` appears to be later GD II / MY16-MY17 market behavior and should not be mixed into the early-GD rebuild.
- `SE` is mixed locally and cannot be cleanly separated by engine size from the repo's current Autotrader feed. Some Carsales examples are `1.8L`, but at least some `SE` rows are `1.6L`, so it is excluded until engine-aware tagging is added.
- `SR` and `SR Premium` behave like the sportier `2.0L` market slice and should not be merged into the mainstream curve.

Year-group guidance from current local evidence:
- current Active GD band: `2012-2016`
- `2017` looks transitional in local evidence and should not be forced into the early-GD curve

Implementation note:
- The current repo year-band logic is derived from saved curve anchor years. The saved `2012`, `2014`, and `2016` anchors intentionally allow `2013` and `2015` Active rows to interpolate without adding unnecessary anchor rows.

Current saved manual V2 curve note:
- `hyundai_i30_gd_hatch_auto_petrol` was manually seeded from pasted Carsales listings rather than the deterministic proposer.
- Saved anchors: `2012`, `2014`, `2016`
- This should be treated as a provisional Carsales-led Active-only curve and rechecked once a proper Carsales evidence layer exists.

Follow-up candidates:
- later GD / GD II `Active X` pass (`2015-2016`)
- separate sport `2.0L` pass for `SR` / `SR Premium`
- engine-aware handling for `SE`

## i30 PD Active Hatch

Base curve:
- `hyundai_i30_pd_hatch_auto_petrol`

Current working interpretation:
- body: `hatch`
- transmission: `auto`
- fuel: `petrol`
- engine: `2.0L`
- intended market slice: exact `Active` PD / PD.V4 / PD2 hatch retail market
- anchor years for current rebuild: `2017`, `2019`, `2022`
- `2018`, `2020`, and `2021` are expected to interpolate between those anchors

Included trims for the current PD pass:
- `Active`
- `Active Smartsense` can remain in scope as an option-pack style Active listing unless later evidence shows it behaves as a separate value lane.

Excluded trims for the current PD pass:
- `Active X`
- `Elite`
- `Premium`
- `Trophy`
- `SE`
- `SR`
- `SR Premium`
- `N Line`

Why these exclusions exist:
- This curve is for exact Active hatch rows only. Higher trim, sport, or Active X rows should not be used as fallback evidence even if they share the same PD generation.
- Later high-km PD evidence is thinner than the 2017-2019 evidence, so 2020-2021 should interpolate until stronger evidence supports separate anchors.
