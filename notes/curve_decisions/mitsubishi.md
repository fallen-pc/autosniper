# Mitsubishi Curve Decisions

## Pajero GLX NT/NW Diesel Automatic SUV

Base curve:
- `mitsubishi_pajero_glx_nt-nw_suv_auto_diesel`

Current working interpretation:
- body: `suv`, with `wagon` accepted as an equivalent source label
- transmission: `auto`
- fuel: `diesel`
- intended market slice: private-sale Mitsubishi Pajero GLX NT/NW diesel automatic SUVs
- anchor years: `2010`, `2012`, `2014`
- buckets use the standard repo grid: `30000`, `60000`, `100000`, `150000`, `200000`
- high-km extension buckets: `225000`, `300000`, matching the shared extension denominations

Included rows for the current pass:
- Pajero GLX NT diesel automatic SUV/wagon rows
- Pajero GLX NW diesel automatic SUV/wagon rows

Excluded rows for the current pass:
- petrol rows
- manual rows
- Exceed rows
- VRX rows
- GLS or Platinum rows

Why:
- The active Grays gaps are GLX diesel automatic Pajeros in the NT/NW period, and the private Carsales evidence is thin but directly aligned to GLX.
- The first curve is deliberately conservative at high kilometres. The `225000` and `300000` extensions are the shared extension denominations for high-km curve work, and the 300k bucket is needed to cover the current live GLX rows above 225k.
- This curve is a retail resale curve built from Carsales/private asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.

## Triton GLX MN Diesel Manual Ute

Base curve:
- `mitsubishi_triton_glx_mn_ute_manual_diesel`

Current working interpretation:
- body: `ute`, with dual-cab/pickup/cab-chassis source labels accepted
- transmission: `manual`
- fuel: `diesel`
- intended market slice: private-sale Mitsubishi Triton GLX MN diesel manual utes
- anchor years: `2011`, `2013`, `2015`
- buckets use the standard repo grid: `30000`, `60000`, `100000`, `150000`, `200000`
- high-km extension buckets: `225000`, `300000`, matching the shared extension denominations

Included rows for the current pass:
- Triton GLX MN diesel manual ute / dual cab rows

Excluded rows for the current pass:
- automatic rows
- petrol rows
- GLX-R / GLXR rows
- GLX+ rows
- GLS / VR rows
- MQ, MR, and MV rows

Why:
- The supplied Carsales evidence is MN GLX manual-only and has enough high-km depth to support the shared extension denominations.
- The current active Triton rows include MN auto, MN GLX-R manual, and MQ rows, so those are intentionally left for separate curves rather than silently merged.
- This curve is a retail resale curve built from Carsales/private asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.

## Carsales/Apify Batch Curves - 2026-06-23

- `mitsubishi_triton_glx_mn_ute_auto_diesel` was built or extended from `25` clean private Carsales/Apify same-lane rows spanning `2009`-`2015`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `mitsubishi_triton_glxr_mn_ute_manual_diesel` was built or extended from `24` clean private Carsales/Apify same-lane rows spanning `2009`-`2015`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve. The `GL-R` badge spelling is treated as an alias for this existing GLX-R lane rather than a duplicate curve.
- `mitsubishi_triton_glxr_mn_ute_auto_diesel` was built or extended from `19` clean private Carsales/Apify same-lane rows spanning `2009`-`2015`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve. The `GL-R` badge spelling is treated as an alias for this existing GLX-R lane rather than a duplicate curve.
- `mitsubishi_pajero_glx_nx_suv_auto_diesel` was built or extended from `21` clean private Carsales/Apify same-lane rows spanning `2015`-`2021`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `mitsubishi_pajero_gls_nx_suv_auto_diesel` was built or extended from `13` clean private Carsales/Apify same-lane rows spanning `2014`-`2020`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `mitsubishi_pajero_exceed_nx_suv_auto_diesel` was built or extended from `11` clean private Carsales/Apify same-lane rows spanning `2014`-`2020`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.

## Pajero NX High-Km Extension - 2026-07-23

- Added the governed `225000` km bucket to the existing GLX, GLS, and Exceed NX diesel automatic SUV curves.
- Each extension continues that anchor year's existing `150000` to `200000` depreciation slope for another `25000` km, rounded conservatively to the nearest `$100`.
- Staged private Carsales evidence contains genuine NX examples above `200000` km in all three trim lanes. The extension preserves the existing retail curve shape rather than refitting the full curve from the thin high-km sample.
- Pajero Sport/QE is explicitly excluded from all three NX matchers. Grays Pajero Sport rows remain separate buy-side evidence and cannot feed Pajero NX historical comparisons.
