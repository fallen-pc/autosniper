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
