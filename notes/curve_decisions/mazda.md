# Mazda Curve Decisions

## Mazda 3 BL Hatch Mainstream Petrol Auto

Base curve:
- `mazda_3_bl_hatch_auto_petrol`

Current working interpretation:
- body: `hatch`
- transmission: `auto`
- fuel: `petrol`
- engine: `2.0L`
- intended market slice: mainstream BL hatch trims grouped into one resale curve

Included trims for the current pass:
- `Neo`
- `Maxx`
- `Maxx Sport`
- `Touring`

Anchor decision:
- saved anchors: `2009`, `2011`, `2013`
- `2010` should interpolate between `2009` and `2011`
- `2012` should interpolate between `2011` and `2013`

Why these anchors were chosen:
- `2010` was too thin and distorted by a very high-km cheap listing
- `2011` and `2013` had much better Carsales support
- `2009` gave a cleaner lower baseline for the earlier BL market

Implementation note:
- Current V2 curve was manually seeded from pasted Carsales listings and should be treated as a provisional Carsales-led curve until a proper Carsales evidence layer exists.
- The stale duplicate `mazda_3_neo_petrol_auto_hatch_bl` curve rows have been removed. Neo still maps to `mazda_3_bl_hatch_auto_petrol` through the V2 group map, so the base curve is the only saved source of truth.
