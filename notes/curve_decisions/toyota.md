# Toyota Curve Decisions

## Corolla Ascent Sedan

Current working interpretation:
- `toyota_corolla_ascent_petrol_auto_sedan_zre152r` is an Ascent sedan lane, not a generic ZRE152R sedan lane.
- `Conquest` is a separate trim and must not be used as fallback evidence for Ascent.

Implementation note:
- `Conquest` is now excluded from Corolla Ascent tagging for the `zre152r`, `zre172r`, and `zre18x` Ascent lanes.
- After retagging, the raw Grays `zre152r` Ascent sold lane contains `42` Ascent rows and no Conquest rows.
- The ZRE152R and ZRE172R sedan price grids now resolve through V2 base curves `toyota_corolla_zre152r_sedan_auto_petrol` and `toyota_corolla_zre172r_sedan_auto_petrol`; the detailed matcher tags no longer carry separate saved curve rows.

## V2 Base Curve Source Of Truth

Current working interpretation:
- When a V2 match tag maps to a saved base curve, the base curve is the source of truth.
- Matcher tags may still appear in tagged evidence and coverage reports, but they should not carry separate saved curve rows when the base exists.

Implementation note:
- Removed stale duplicate matcher-tag curve rows for `toyota_corolla_ascent_petrol_auto_hatch_zre18x`, `toyota_corolla_ascent-sport_petrol_auto_hatch_zre18x`, and `toyota_yaris_yr_petrol_auto_hatch_ncp90r`.
- The Toyota hatch split still resolves through `toyota_corolla_ascent_zre182r_hatch_auto_petrol` and `toyota_corolla_ascent-sport_zre182r_hatch_auto_petrol`.
- The Yaris matcher still resolves through `toyota_yaris_ncp90r_hatch_auto_petrol`.

## Yaris Ascent NCP130R Hatch Auto Petrol

- `toyota_yaris_ascent_ncp130r_hatch_auto_petrol` is the saved V2 base curve for Yaris Ascent NCP130R hatch/auto/petrol evidence.
- `toyota_yaris_ascent_petrol_auto_hatch_ncp130r` is the matcher tag that feeds that base curve through the V2 group map.
- YR, YRS, SX, ZR, GR, manual, hybrid, sedan, and Yaris Cross rows must not be folded into this curve.
- A 2026-06-23 Carsales/Apify private-market scrape supplied `48` same-lane Ascent NCP130R hatch/auto/petrol asking-price rows from `2014` through `2020`.
- The saved grid uses anchors `2014`, `2016`, `2018`, and `2020` with the extended high-km buckets `225000` and `300000`; the `2020` anchor is conservative because the direct evidence is thin.
- This is a retail resale curve built from Carsales/private asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.
- The MZEA12R petrol hatch now resolves through the V2 base curve `toyota_corolla_mzea12r_hatch_auto_petrol`; the detailed matcher tag `toyota_corolla_ascent-sport_petrol_auto_hatch_mzea12r` no longer carries separate saved curve rows.
- The Camry AXVH71R Ascent Hybrid lane now resolves through the V2 base curve `toyota_camry_axvh71r_sedan_auto_hybrid`; the detailed matcher tag `toyota_camry_ascent_hybrid_auto_sedan_axvh71r` no longer carries separate saved curve rows.
- The ZWE211R hybrid hatch now resolves through the V2 base curve `toyota_corolla_zwe211r_hatch_auto_hybrid`; the detailed matcher tag `toyota_corolla_ascent-sport_hybrid_auto_hatch_zwe211r` no longer carries separate saved curve rows.
- The ZWE219R hybrid hatch now resolves through the V2 base curve `toyota_corolla_zwe219r_hatch_auto_hybrid`; the detailed matcher tag `toyota_corolla_ascent-sport_hybrid_auto_hatch_zwe219r` no longer carries separate saved curve rows.
- The Corolla sedan split now resolves through V2 base curves `toyota_corolla_zre152r_sedan_auto_petrol` and `toyota_corolla_zre172r_sedan_auto_petrol`; their detailed Ascent matcher tags no longer carry separate saved curve rows.
- The Camry ASV70R petrol sedan now resolves through the V2 base curve `toyota_camry_asv70r_sedan_auto_petrol`; the detailed matcher tag `toyota_camry_ascent_petrol_auto_sedan_asv70r` no longer carries separate saved curve rows.

## Corolla Ascent Sport MZEA12R Hatch

Current working interpretation:
- `toyota_corolla_mzea12r_hatch_auto_petrol` is the saved V2 base curve for Corolla Ascent Sport MZEA12R hatch/auto/petrol evidence.
- `toyota_corolla_ascent-sport_petrol_auto_hatch_mzea12r` remains the matcher tag that feeds that base curve through the V2 group map.
- SX, ZR, hybrid, sedan, manual, and non-MZEA12R rows must not be folded into this lane.

Evidence snapshot:
- The existing saved grid is a `2019/2021/2024` anchor set and was moved onto the V2 base tag without repricing.
- Local Autotrader evidence has `34` matched Ascent Sport MZEA12R hatch/auto/petrol rows across `2019-2024`.
- No matched Grays sold rows are currently present for this lane in the sold export.

## Camry Ascent Hybrid AXVH71R

Current working interpretation:
- `toyota_camry_axvh71r_sedan_auto_hybrid` is the saved V2 base curve for exact Ascent Hybrid AXVH71R sedan/auto/hybrid evidence.
- `toyota_camry_ascent_hybrid_auto_sedan_axvh71r` remains the matcher tag that feeds that base curve through the V2 group map.
- `Ascent Sport Hybrid` is now a separate saved trim/value lane and must not be folded into the Ascent Hybrid curve just to increase evidence count.
- `2025` Ascent Hybrid rows are same-trim evidence, but they are outside the current saved curve anchor range and should be reviewed as a deliberate curve-extension task.

Evidence snapshot:
- The saved Ascent Hybrid grid is a `2018/2020/2022/2024` anchor set and was moved onto the V2 base tag without repricing.
- The current local Autotrader recent-market cache has `10` matched Ascent Hybrid rows for the current lane plus `4` same-trim `2025` rows rejected as out-of-scope year.
- The current local Autotrader recent-market cache also has `10` Ascent Sport Hybrid rows; these stay separate from the plain Ascent lane.
- Grays sold has `2` matched Ascent Hybrid AXVH71R rows.
- Grays sold also has `5` Ascent Sport Hybrid AXVH71R rows and `2` Ascent Hybrid AXVH70R rows; these should not be silently merged into AXVH71R Ascent Hybrid.

## Camry Ascent Sport Hybrid AXVH71R

Current working interpretation:
- `toyota_camry_ascent-sport_axvh71r_sedan_auto_hybrid` is the saved V2 base curve for Camry Ascent Sport Hybrid AXVH71R sedan/auto/hybrid evidence.
- `toyota_camry_ascent-sport_hybrid_auto_sedan_axvh71r` is the matcher tag that feeds that base curve through the V2 group map.
- Plain `Ascent Hybrid`, `SX`, `SL`, `Atara`, petrol, and AXVH70R rows must not be folded into this lane.

Evidence snapshot:
- A 2026-04-16 private Carsales check supplied `21` same-lane Ascent Sport Hybrid AXVH71R sedan/auto/hybrid asking-price rows: `5` for `2018`, `10` for `2019`, and `6` for `2020`.
- The saved grid uses a `2018/2019/2020` anchor set derived from that private-market slice while excluding obvious high and low asking-price outliers from anchoring.
- Grays sold has `5` same-lane Ascent Sport Hybrid AXVH71R sold rows across `2019-2020`.
- The current local Autotrader recent-market cache has broader Ascent Sport Hybrid Camry rows, but the cached rows do not currently expose clean AXVH71R series proof, so they were not used as exact-series evidence for this saved lane.

## Camry Ascent ASV70R Petrol

Current working interpretation:
- `toyota_camry_asv70r_sedan_auto_petrol` is the saved V2 base curve for Camry Ascent ASV70R sedan/auto/petrol evidence.
- `toyota_camry_ascent_petrol_auto_sedan_asv70r` is the matcher tag that feeds that base curve through the V2 group map.
- AXVH70R/AXVH71R hybrid rows, Ascent Sport, SX, SL, Atara, manual, and non-ASV70R rows must not be folded into this petrol lane.

Evidence snapshot:
- A 2026-04-17 private Carsales check supplied `15` same-lane Ascent ASV70R sedan/auto/petrol rows: `7` for `2018`, `7` for `2019`, and `1` for `2020`.
- The current local Autotrader recent-market cache has `68` same-lane Ascent ASV70R rows: `15` for `2018`, `14` for `2019`, `10` for `2020`, `17` for `2021`, and `12` for `2022`.
- The saved grid uses `2018/2020/2022` anchors so `2019` and `2021` interpolate.
- Grays sold currently has only `1` same-lane ASV70R row, and that sale price is not useful valuation evidence, so the curve is intentionally live-market built from Carsales plus Autotrader.

## Corolla Ascent ZRE182R Hatch

Current working interpretation:
- `toyota_corolla_ascent_zre182r_hatch_auto_petrol` is the saved V2 base curve for Ascent-only ZRE182R hatch/auto/petrol evidence.
- `toyota_corolla_ascent_petrol_auto_hatch_zre18x` remains the matcher tag that feeds that base curve through the V2 group map.
- `Ascent Sport`, `Levin`, `SX`, `ZR`, `Conquest`, hybrid, and manual rows must not be folded into this Ascent curve to increase evidence count.

Evidence snapshot:
- A 2026-04-12 private Carsales check supplied `30` same-lane Ascent ZRE182R hatch/auto/petrol asking-price rows.
- The check supported keeping the current saved `2013/2015/2018` anchor grid as-is; the pasted rows were close overall and did not justify repricing.
- Treat future changes to this curve as a separate repricing review, not as tag-alignment cleanup.

## Corolla Ascent Sport Hybrid ZWE211R Hatch

Current working interpretation:
- `toyota_corolla_zwe211r_hatch_auto_hybrid` is the saved V2 base curve for Ascent Sport Hybrid ZWE211R hatch/auto/hybrid evidence.
- `toyota_corolla_ascent-sport_hybrid_auto_hatch_zwe211r` remains the matcher tag that feeds that base curve through the V2 group map.
- Petrol, SX, ZR, Levin, GR, manual, Axio, and Hybrid EX rows must not be folded into this curve.

Evidence snapshot:
- A 2026-04-12 private Carsales check supplied `17` same-lane Ascent Sport Hybrid ZWE211R hatch/auto/hybrid asking-price rows.
- The check included `2018` and `2019` rows, but the saved curve remains a `2020/2021/2022` anchor grid for now.
- Local Autotrader evidence supports the current `2020` and `2021` saved values closely; the `2022` private sample sits lower but does not justify an automatic repricing without a separate review.
- The Autotrader matching range now includes `2018-2022` for ZWE211R; this maps `2018/2019` Ascent Sport Hybrid hatch rows into the correct evidence lane without adding price anchors.
- Grays sold matching now has `4` same-lane ZWE211R rows after moving one stale `2019` Ascent Sport Hybrid hatch row out of `[OUT_OF_SCOPE_YEAR]`.

## Corolla Ascent Sport Hybrid ZWE219R Hatch

Current working interpretation:
- `toyota_corolla_zwe219r_hatch_auto_hybrid` is the saved V2 base curve for Ascent Sport Hybrid ZWE219R hatch/auto/hybrid evidence.
- `toyota_corolla_ascent-sport_hybrid_auto_hatch_zwe219r` remains the matcher tag that feeds that base curve through the V2 group map.
- Keep ZWE219R separate from ZWE211R; this is a newer hybrid hatch series/value lane.

Evidence snapshot:
- Local Autotrader evidence has `34` matched ZWE219R Ascent Sport Hybrid rows: `26` for `2024` and `8` for `2025`.
- No matched Grays sold ZWE219R rows are currently present in the sold export.
- The current `2024/2025` price grid was retained while moving the saved rows onto the V2 base tag. The `2025` Autotrader sample sits below the saved grid, so any 2025 adjustment should be a separate repricing review.
- The Autotrader matching range now includes `2023-2025` for ZWE219R; this maps `2023` Ascent Sport Hybrid hatch rows into the newer hybrid hatch evidence lane without adding price anchors.

## Carsales/Apify Batch Curves - 2026-06-23

- `toyota_camry_altise_acv40r_sedan_auto_petrol` was built or extended from `50` clean private Carsales/Apify same-lane rows spanning `2006`-`2011`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `toyota_camry_altise_acv36r_sedan_auto_petrol` and `toyota_camry_altise_mcv36r_sedan_auto_petrol` were built from clean private Carsales/Apify same-lane Altise automatic sedan evidence spanning `2003`-`2006`. The ACV36R and MCV36R engines stay separate, and ACV40R/ASV50R/manual/nearby trims remain excluded.
- `toyota_camry_atara-s_asv50r_sedan_auto_petrol` was built from `8` clean private Carsales/Apify same-lane Atara S automatic sedan rows spanning `2011`-`2016`. Atara SX, Atara SL, Altise, hybrid, manual, and nearby generation rows remain separate; Grays sold evidence is not used to reprice this retail curve.
- `toyota_corolla_ascent_zre152r_hatch_auto_petrol` was built or extended from `34` clean private Carsales/Apify same-lane rows spanning `2007`-`2012`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `toyota_corolla_ascent-sport_zre182r_hatch_manual_petrol` is an existing manual curve; the 2026-06-26 matcher repair removed a self-excluding `ascent` keyword so clean Ascent Sport manual rows feed this curve without absorbing plain Ascent manual rows.
- `toyota_yaris_yr_ncp90r_hatch_manual_petrol` was built or extended from `20` clean private Carsales/Apify same-lane rows spanning `2006`-`2011`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `toyota_yaris_yr_ncp130r_hatch_auto_petrol` was built or extended from `11` clean private Carsales/Apify same-lane rows spanning `2011`-`2014`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `toyota_yaris_yrs_ncp91r_hatch_auto_petrol` was built or extended from `10` clean private Carsales/Apify same-lane rows spanning `2005`-`2011`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `toyota_yaris_ascent_ncp130r_hatch_manual_petrol` was built or extended from `15` clean private Carsales/Apify same-lane rows spanning `2014`-`2019`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
- `toyota_corolla_ascent-sport_zre182r_hatch_manual_petrol` was built or extended from `19` clean private Carsales/Apify same-lane rows spanning `2012`-`2016`. Nearby trim, body, transmission, fuel, and generation lanes remain separate; Grays sold evidence is not used to reprice this retail curve.
