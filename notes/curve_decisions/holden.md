# Holden Curve Decisions

## Commodore VF Petrol Automatic Sedan

Base curves:
- `holden_commodore_evoke_vf_sedan_auto_petrol`
- `holden_commodore_sv6_vf_sedan_auto_petrol`
- `holden_commodore_evoke_vf_wagon_auto_petrol`
- `holden_commodore_sv6_vf_wagon_auto_petrol`

Current working interpretation:
- body: `sedan` or `wagon`, saved as separate curves
- transmission: `auto`
- fuel: `petrol`
- series: `VF`
- anchor years: `2013`, `2014`, `2015`
- buckets use the standard extended grid: `30000`, `60000`, `100000`, `150000`, `200000`, `225000`, `300000`

Included rows for the current pass:
- Commodore VF Evoke 3.0L petrol automatic sedans
- Commodore VF SV6 3.6L petrol automatic sedans
- Commodore VF Evoke 3.0L petrol automatic wagons
- Commodore VF SV6 3.6L petrol automatic wagons

Excluded rows for the current pass:
- utes
- manual rows
- diesel, LPG, gas, gas-only, and hybrid rows
- SS, SS V, Redline, Storm, HSV, and other V8/performance rows
- older VE and VE Series II rows

Why:
- The supplied Carsales evidence showed a clear retail separation between Evoke 3.0L and SV6 3.6L sedans.
- Combining the badges would overprice the cheaper Evoke lane, so the VF pass keeps them as separate curves.
- Sedan and wagon are also kept separate because wagon pricing had enough direct evidence and a different buyer lane.
- This curve is a retail resale curve built from Carsales/private asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.
