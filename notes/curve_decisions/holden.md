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

## Commodore VE Petrol Automatic Sedan/Wagon

Base curves:
- `holden_commodore_omega_ve_sedan_auto_petrol`
- `holden_commodore_sv6_ve_sedan_auto_petrol`
- `holden_commodore_omega_ve_wagon_auto_petrol`
- `holden_commodore_sv6_ve_wagon_auto_petrol`

Current working interpretation:
- body: `sedan` or `wagon`, saved as separate curves
- transmission: `auto`
- fuel: `petrol`
- series: `VE`
- Omega sedan anchor years: `2007`, `2009`, `2010`
- SV6 sedan anchor years: `2007`, `2008`, `2009`
- Omega wagon anchor years: `2008`, `2009`, `2010`
- SV6 wagon anchor years: `2008`, `2009`, `2010`
- buckets use the extended Holden grid: `30000`, `60000`, `100000`, `150000`, `200000`, `225000`, `300000`

Included rows for the current pass:
- Commodore VE Omega petrol automatic sedans and wagons
- Commodore VE SV6 petrol automatic sedans and wagons

Excluded rows for the current pass:
- VE Series II rows
- VF, VZ, VY, VX, and VT rows
- utes
- manual rows
- diesel, LPG, dual-fuel, gas, gas-only, and hybrid rows
- SS, SS V, Redline, Storm, HSV, Calais, Berlina, Executive, International, Lumina, Evoke, and other materially different badge rows

Why:
- The Apify Carsales scrape provided direct private listing evidence for VE Omega and SV6 sedan/wagon lanes.
- VE Series II has enough signal to review separately, but it is not folded into the plain VE curves.
- These curves are retail resale curves built from Carsales/private asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.

## Commodore VE Series II Omega Petrol Automatic Wagon

Base curve:
- `holden_commodore_omega_ve-series-ii_wagon_auto_petrol`

Current working interpretation:
- body: `wagon`
- transmission: `auto`
- fuel: `petrol`
- series: `VE Series II`
- badge: `Omega`
- anchor years: `2010`, `2011`, `2012`, `2013`
- buckets use the extended Holden grid: `30000`, `60000`, `100000`, `150000`, `200000`, `225000`, `300000`

Included rows for the current pass:
- Commodore VE Series II Omega petrol automatic wagons

Excluded rows for the current pass:
- plain VE rows
- VF, VZ, VY, VX, and VT rows
- sedans and utes
- manual rows
- diesel, LPG, dual-fuel, gas, gas-only, and hybrid rows
- SV6, SS, SS V, Redline, Storm, HSV, Calais, Berlina, Executive, International, Lumina, Evoke, and other materially different badge rows

Why:
- The Apify Carsales scrape provided 16 private Omega wagon rows for VE Series II, mostly in the high-km range.
- VE Series II is kept separate from plain VE because it has its own direct evidence and year band.
- The 2013 anchor is conservative because it has only one direct row, but it keeps 2013 Omega wagons inside the supported year band.
- This curve is a retail resale curve built from Carsales/private asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.
