# Hyundai Curve Decisions

## i30 GD Early Mainstream Hatch

Base curve:
- `hyundai_i30_gd_hatch_auto_petrol`

Current working interpretation:
- body: `hatch`
- transmission: `auto`
- fuel: `petrol`
- intended market slice: early mainstream GD hatch retail market
- anchor years for current rebuild: `2012`, `2014`
- `2013` is expected to interpolate between those anchors

Included trims for the current early-GD pass:
- `Active`
- `Elite`
- `Premium`
- `Trophy`

Excluded trims for the current early-GD pass:
- `Active X`
- `SE`
- `SR`
- `SR Premium`

Why these exclusions exist:
- `Active X` appears to be later GD II / MY16-MY17 market behavior and should not be mixed into the early-GD rebuild.
- `SE` is mixed locally and cannot be cleanly separated by engine size from the repo's current Autotrader feed. Some Carsales examples are `1.8L`, but at least some `SE` rows are `1.6L`, so it is excluded until engine-aware tagging is added.
- `SR` and `SR Premium` behave like the sportier `2.0L` market slice and should not be merged into the mainstream curve.

Year-group guidance from current local evidence:
- safest early mainstream band: `2012-2014`
- later GD / GD II behavior should be reviewed separately
- `2017` looks transitional in local evidence and should not be forced into the early-GD curve

Implementation note:
- The current repo year-band logic is derived from saved curve anchor years. That means `2012` rows may still appear as out-of-scope until the rebuilt curve with a `2012` anchor is saved.

Current saved manual V2 curve note:
- `hyundai_i30_gd_hatch_auto_petrol` was manually seeded from pasted Carsales listings rather than the deterministic proposer.
- Saved anchors: `2012`, `2014`
- This should be treated as a provisional Carsales-led curve and rechecked once a proper Carsales evidence layer exists.

Follow-up candidates:
- later GD / GD II mainstream `1.8L` pass (`2015-2016`)
- separate sport `2.0L` pass for `SR` / `SR Premium`
- engine-aware handling for `SE`
