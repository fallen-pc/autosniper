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

## Accent Active RB Automatic Hatch

Base curve:
- `hyundai_accent_active_rb_hatch_auto_petrol`

Current working interpretation:
- body: `hatch`
- transmission: `auto`
- fuel: `petrol`
- intended market slice: private-sale Hyundai Accent Active RB/RB2/RB3/RB4 automatic petrol hatches
- anchor years: `2013`, `2015`, `2017`
- buckets use the standard repo grid: `30000`, `60000`, `100000`, `150000`, `200000`

Included rows for the current pass:
- Accent Active hatch automatic/CVT petrol rows

Excluded rows for the current pass:
- manual rows
- sedan rows
- diesel or hybrid rows
- Sport, Elite, or other non-Active trims

Why:
- The early 1.6L and later 1.4L Active hatches are held as one budget commuter lane unless future evidence justifies an engine split.
- This curve is a retail resale curve built from Carsales/private asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.

## iLoad TQ Diesel Automatic Van

Base curve:
- `hyundai_iload_tq_van_auto_diesel`

Current working interpretation:
- body: `van`
- transmission: `auto`
- fuel: `diesel`
- intended market slice: private-sale Hyundai iLoad TQ diesel automatic vans
- anchor years for current rebuild: `2012`, `2014`, `2016`
- buckets use the standard repo grid: `30000`, `60000`, `100000`, `150000`, `200000`
- standard low-km buckets are conservative extrapolations from the observed 57k-203k private asking band; 250k+ private rows were used only as context for the 200k bucket and not added as extra curve buckets
- the 2026-05-19 refresh used 100+ private Carsales rows from pages 1-7; very high asking rows around `$30k-$38k` were treated as upper-market outliers rather than midpoint evidence

Included rows for the current pass:
- iLoad van automatic diesel rows only

Excluded rows for the current pass:
- manual iLoad rows
- iLoad Crew rows
- iMax people mover rows
- petrol rows

Why these exclusions exist:
- Manual vans, crew vans, and iMax people movers are separate value lanes and should not be silently merged into the automatic van resale curve.
- This curve is a retail resale curve built from Carsales/private asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.

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

## Carsales/Apify Batch Curves - 2026-06-23

- `hyundai_accent_sport_rb_hatch_auto_petrol` was built or extended from `35` clean private Carsales/Apify same-lane rows spanning `2017`-`2019`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `hyundai_iload_tq_van_manual_diesel` was built or extended from `35` clean private Carsales/Apify same-lane rows spanning `2008`-`2015`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `hyundai_iload_tq_van_auto_diesel` was built or extended from `79` clean private Carsales/Apify same-lane rows spanning `2015`-`2021`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
