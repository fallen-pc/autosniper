# Ford Curve Decisions

## Territory SZ TX/TS Diesel Automatic SUV

Base curve:
- `ford_territory_sz_suv_auto_diesel`

Current working interpretation:
- body: `suv`, with `wagon` accepted as an equivalent source label
- transmission: `auto`
- fuel: `diesel`
- intended market slice: private-sale Ford Territory SZ/SZ MkII TX and TS diesel automatic SUVs
- anchor years: `2011`, `2013`, `2016`
- buckets use the standard repo grid: `30000`, `60000`, `100000`, `150000`, `200000`

Included rows for the current pass:
- Territory TX diesel automatic SUV/wagon rows
- Territory TS diesel automatic SUV/wagon rows
- RWD and AWD rows are held together for now

Excluded rows for the current pass:
- petrol rows
- manual rows
- Ghia or Titanium rows
- turbo petrol rows

Why:
- Current active Grays rows are mixed TX/TS Territory diesel automatic stock, and the provided private Carsales evidence was gathered with TX and TS together.
- TS and lower-km rows show some upper-market asks, so the first curve is deliberately conservative and combined rather than using high asking outliers as midpoint evidence.
- This curve is a retail resale curve built from Carsales/private asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.

## Carsales/Apify Batch Curves - 2026-06-23

- `ford_territory_titanium_sz_suv_auto_diesel` was built or extended from `38` clean private Carsales/Apify same-lane rows spanning `2011`-`2014`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `ford_territory_sy_suv_auto_petrol` was built from private Carsales/Apify SY/SY MkII automatic petrol TX/TS/Ghia/SR evidence spanning `2006`-`2011`. It intentionally excludes SZ, SX, Titanium, turbo petrol, diesel, and manual rows.
- `ford_territory_sz_suv_auto_petrol` was built from private Carsales/Apify SZ/SZ MkII automatic petrol TX/TS evidence spanning `2011`-`2016`. It intentionally excludes SY, SX, Titanium, Ghia, turbo petrol, diesel, and manual rows.

## Carsales/Apify Batch Curves - 2026-07-13

- `ford_focus_trend_lz_hatch_auto_petrol` was built from `7` clean private Carsales/Apify Focus Trend LZ automatic petrol hatch rows spanning `2015`-`2016`. LW, Sport, Titanium, Ambiente, ST, XR5, manual, diesel, and non-hatch lanes remain separate.
