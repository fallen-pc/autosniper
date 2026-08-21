# Changelog

## 2026-08-21
- Added governed Ford Kuga Ambiente TF AWD petrol, Holden Barina TK automatic hatch, and Volkswagen Golf 103TSI Highline A7 curves from exact private Carsales evidence backed by live Grays demand, adding 56 curve rows and increasing canonical curve coverage from 208 to 211 tags.

## 2026-08-14
- Added governed Ford Kuga Trend and Titanium TF diesel, Mazda 3 Neo BL automatic sedan, and Holden Barina TK manual curves from exact private Carsales evidence, increasing restricted Grays sold coverage from 4,749 to 4,829 vehicles.
- Added governed Hyundai i45 Active YF, Nissan Dualis ST J10 CVT, Ford Mondeo LX TDCi MC wagon, Volkswagen Golf GTI VI automatic, and Volvo XC60 T5 DZ curves from exact private Carsales evidence, increasing restricted Grays sold coverage from 4,829 to 4,920 vehicles.

## 2026-08-10
- Added governed Mercedes-Benz B200 W245, Mercedes-Benz C200 BlueEFFICIENCY W204, and Nissan X-Trail ST T30 curves from recovered private Carsales evidence, increasing restricted Grays sold coverage from 4,696 to 4,749 vehicles.

## 2026-08-09
- Added five further live-Grays-backed lanes from private Carsales Apify batch `7WqoauuNvqzoVM5jO`: BMW X5 xDrive30d F15, Audi A4 1.8 TFSI B8 CVT, Mazda 3 Neo BL, Jeep Cherokee Sport 4x2 KL9, and Nissan Micra K12, with a reproducible builder and governed snapshot.
- Reconciled the accumulated July/August governed curve campaign into source control: the saved curve set grows from 115 to 191 canonical tags, with its manifest-linked snapshots, matcher/config support, exact-lane regression coverage, and durable accepted/rejected decision records.
- Hardened Carsales/Apify ingestion for exact URL batches and the alternate flat actor schema, including per-target paid-scrape preflight, deferred imports for non-terminal runs, stable identified-row merging, and hybrid/series normalization.
- Added reusable Grays-first curve worklists/builders and split vehicle/repair classification PDF generators, while keeping paid-run JSON, backup CSVs, model-training outputs, and live runtime queues outside the governed commit.
- Passed vehicle class into repair assessment from monitoring/training paths and simplified AI Analysis cards so the listing identity remains visible above the tabbed detail content.

## 2026-07-23
- Kept Pajero Sport/QE rows out of Pajero NX GLX, GLS, and Exceed matching, and added governed `225000` km retail-curve cells for those three NX lanes using the existing same-lane depreciation shape.

## 2026-07-18
- Added Autotrader lifecycle confidence signals to AI Analysis: matched listings now retain first/last seen and sold/removed status, fast near-curve removals boost confidence, stale near-curve active listings warn, and Autotrader-vs-Carsales curve mismatches surface as non-blocking risk flags.
- Removed the hidden legacy Curve Builder page and stripped the old AI/OpenAI/Ollama curve writer internals from `scripts/process_curve_candidates.py`; Curve Builder V2 is now the only save-capable curve-building surface.
- Added the July staged Carsales curve batches: twenty-one narrow private-market lanes across Toyota Aurion/Corolla/Kluger, Kia Cerato, Holden Cruze/Barina/Calais/Commodore, Ford Focus, Hyundai i30/Elantra, Nissan X-Trail, Isuzu MU-X, and Mazda CX-5, with governed curve snapshots through `curves_20260717T064125Z.csv`.
- Consolidated curve pricing onto Curve Builder V2 only. Legacy AI curve writing in `scripts/process_curve_candidates.py` is disabled, and Curve Pipeline now handles candidate queue refresh plus Autotrader follow-up only. Autotrader remains comparison evidence, not a curve-pricing input.

## 2026-07-01
- Added thirteen narrow Toyota Kluger, Mitsubishi Outlander, Nissan X-Trail, and Subaru Forester retail curve lanes from private Carsales/Apify evidence, with allowed-variant gates, V2 group mappings, supported-universe rows, and a governed curve snapshot.

## 2026-06-23
- Repaired scraped-data utilisation for existing curves: Corolla Ascent Sport ZRE182R manual rows now feed the existing manual curve, and first-generation 2014 MU-X LS-U/LS-T rows now have conservative early-year anchors while 2021+ MU-X rows remain separate newer-generation targets.
- Added Toyota Camry Atara S ASV50R automatic petrol sedan and Volkswagen Golf V/A5 GTI automatic petrol hatch curves from private Carsales/Apify evidence, and repaired Triton `GL-R` aliasing plus Mazda `CX-5` spelling so existing governed curves pick up those rows instead of needing duplicates.
- Added Toyota Camry XV30 Altise ACV36R/MCV36R automatic petrol sedan curves and Volkswagen Golf V Comfortline / Golf VI Trendline automatic petrol hatch curves from existing private Carsales/Apify evidence, prioritised by historical Grays sold volume without using Grays sold prices for retail curve repricing.
- Added Ford Territory SY/SY MkII petrol automatic SUV, Ford Territory SZ/SZ MkII petrol automatic SUV, and Holden Captiva CG petrol/diesel automatic SUV curves from private Carsales/Apify evidence, prioritised by historical Grays sold volume.
- Added Volkswagen Golf VI Comfortline automatic petrol and diesel hatch curves from a gated private Carsales/Apify scrape, keeping GTI, Golf R, Trendline, Highline, wagon, and manual lanes separate.
- Added Isuzu MU-X LS-M, LS-U, and LS-T automatic diesel SUV curves from a gated private Carsales/Apify scrape, including high-km buckets for current active MU-X coverage.
- Added a Carsales/Apify batch of 20 new retail curve lanes across Toyota, Hyundai, Ford, Mitsubishi, and Mazda, and extended the Hyundai iLoad automatic diesel curve with newer private-market anchors.
- Added the `toyota_yaris_ascent_ncp130r_hatch_auto_petrol` curve from private Carsales/Apify Yaris Ascent NCP130R automatic hatch evidence, keeping YR/YRS/SX/ZR/GR/manual/hybrid/Cross rows out of the matcher.

## 2026-06-19
- Added a separate Holden Commodore VE Series II Omega petrol automatic sedan curve from private Carsales/Apify evidence, keeping the sedan and wagon Series II Omega lanes separate.
- Added a separate Holden Commodore VE Series II Omega petrol automatic wagon curve from private Carsales/Apify evidence, keeping plain VE, SV6, VF, and gas-only rows out of the matcher.
- Added separate Holden Commodore VE petrol automatic sedan/wagon curves for `Omega` and `SV6` from private Carsales/Apify evidence, keeping VE Series II, VF, gas/dual-fuel, and materially different badges out of the matcher.
- Saved the governed VE curve artifact snapshot and manifest entry for the new Holden Commodore VE lanes.

## 2026-06-16
- Added separate Holden Commodore VF petrol automatic wagon curves for `Evoke` and `SV6` from private Carsales evidence, excluding gas-only rows and keeping sedan/wagon lanes separate.
- Added separate Holden Commodore VF petrol automatic sedan curves for `Evoke` and `SV6` from private Carsales evidence, keeping wagons, utes, SS/V8/performance rows, and older VE lanes out of the matcher.

## 2026-06-02
- Added standard same-lane `225000` and `300000` km high-km extensions across existing curve tags, preserving existing Carsales-led extension rows and using lane-level depreciation from the existing curve shape rather than Grays sold-price repricing.

## 2026-05-22
- Added the `mitsubishi_triton_glx_mn_ute_manual_diesel` curve from private Carsales Triton GLX MN manual diesel ute evidence, using the standard grid plus shared `225000` and `300000` extension denominations.
- Extended the `mitsubishi_pajero_glx_nt-nw_suv_auto_diesel` curve with the shared `300000` km high-km extension denomination so current GLX active rows above 225k remain in valuation range.
- Extended the `mitsubishi_pajero_glx_nt-nw_suv_auto_diesel` curve with the repo-standard `225000` km extension denomination from private Carsales high-km Pajero GLX evidence.
- Added the `mitsubishi_pajero_glx_nt-nw_suv_auto_diesel` standard-grid retail resale curve from private Carsales Pajero GLX NT/NW diesel automatic SUV evidence, with NT and NW matcher rows mapped into one conservative base curve.
- Added the `ford_territory_sz_suv_auto_diesel` standard-grid retail resale curve from private Carsales Territory SZ/SZ MkII TX and TS diesel automatic SUV evidence, plus the first Ford matcher support.
- Added the `hyundai_accent_active_rb_hatch_auto_petrol` standard-grid retail resale curve from private Carsales Accent Active RB hatch automatic petrol evidence, plus supported-universe and allowed-variant mapping for Active automatic/CVT hatch rows.

## 2026-05-19
- Added the `hyundai_iload_tq_van_auto_diesel` retail resale curve from private Carsales iLoad TQ diesel automatic van evidence, plus the supported-universe and allowed-variant mapping needed to classify automatic iLoad vans while keeping manual, Crew, and iMax rows out of the lane.
- Refined the `hyundai_iload_tq_van_auto_diesel` standard five-bucket grid with additional private Carsales pages, lifting the normal 2012-2016 automatic van midpoints while treating very high asking rows as upper-market outliers rather than midpoint evidence.

## 2026-05-18
- Added a retail-only `225000` km bucket for the `2013` `toyota_corolla_ascent_zre182r_hatch_auto_petrol` curve from private Carsales Corolla Ascent hatch evidence, extending the high-km resale curve without using Grays sold prices for repricing.

## 2026-04-24
- Added the Hyundai ix35 Elite LM base curve as `hyundai_ix35_elite_lm_wagon_auto_petrol` with `2010/2012/2014` anchors and the standard `30k/60k/100k/150k/200k` bucket grid, then wired the exact Elite LM match tag into the V2 group map and supported curve universe as a conservative family lane.
- Added the Hyundai Getz SX TB manual base curve as `hyundai_getz_sx_tb_hatch_manual_petrol` with `2007/2009/2011` anchors and the standard `30k/60k/100k/150k/200k` bucket grid, then wired the exact SX TB manual match tag into the V2 group map and supported curve universe as a separate lane below the automatic curve.
- Completed current observed curve coverage at `45/45` tags and cleaned up the remaining Streamlit launcher pages plus audit snapshot writing so generated restricted audit CSVs stay readable across schema changes.
- Added the Hyundai Getz SX TB automatic base curve as `hyundai_getz_sx_tb_hatch_auto_petrol` with `2008/2010/2011` anchors and the standard `30k/60k/100k/150k/200k` bucket grid, then wired the exact SX TB automatic match tag into the V2 group map and supported curve universe while leaving manual separate.
- Added the Hyundai ix35 SE LM petrol base curve as `hyundai_ix35_se_lm_wagon_auto_petrol` with `2013/2014/2015` anchors and the standard `30k/60k/100k/150k/200k` bucket grid, then wired the exact SE LM match tag into the V2 group map and supported curve universe while leaving Elite separate.
- Added the Mazda CX-5 Maxx Sport diesel KE-family base curve as `mazda_cx5_maxx-sport_ke_wagon_auto_diesel` with `2012/2014/2016` anchors and the standard `30k/60k/100k/150k/200k` bucket grid, then wired the exact Maxx Sport diesel match tag into the V2 group map and supported curve universe.
- Added the Camry Altise `ASV50R` petrol sedan base curve as `toyota_camry_asv50r_sedan_auto_petrol` with `2013/2015/2017` anchors and the standard `30k/60k/100k/150k/200k` bucket grid, then wired the exact Altise match tag into the V2 group map and supported curve universe.

## 2026-04-17
- Saved the Camry Ascent ASV70R petrol sedan curve as `toyota_camry_asv70r_sedan_auto_petrol` with `2018/2020/2022` anchors, moved the old matcher-tag rows onto the V2 base tag, and marked the lane `live_now`.

## 2026-04-12
- Removed stale duplicate matcher-tag curve rows where a V2 base curve already exists, so Toyota hatch, Yaris, and Mazda 3 BL valuation now have one curve source of truth instead of competing matcher/base rows.
- Tightened Corolla Ascent tagging so `Conquest` rows no longer feed the `zre152r` or `zre172r` Ascent lanes; the raw Grays `zre152r` Ascent sold lane now contains `42` Ascent rows and no Conquest rows.
- Rebuilt the Hyundai i30 PD Active hatch curve as an exact Active-only lane with `2017/2019/2022` anchors; `2018`, `2020`, and `2021` interpolate.
- Tightened Hyundai i30 PD tagging so `Active X`, higher trims, sport trims, and `N Line` no longer feed the Active valuation curve.
- Retagged local Autotrader and Grays evidence after the Hyundai PD update: Autotrader now has `114` PD Active recent-market rows, Grays sold has `21` raw PD Active rows, and governance coverage sees `24` observed PD rows across active/sold/static.
- Rebuilt the Hyundai i30 GD Active hatch curve as an exact Active-only lane with `2012/2014/2016` anchors and removed the stale duplicate matcher-tag curve rows.
- Tightened Hyundai i30 GD tagging so `Elite`, `Premium`, `Trophy`, `Active X`, `SE`, `SR`, and `SR Premium` no longer feed the Active valuation curve.
- Rebuilt the restricted Grays datasets and refreshed governance coverage after the Hyundai tag/curve update.

## 2026-04-10
- Split the Toyota Corolla `zre182r` hatch family by trim in the supported curve universe and V2 group mapping so `ascent` and `ascent-sport` no longer share one base curve.
- Added a governed manual/provisional Ascent hatch curve for `toyota_corolla_ascent_zre182r_hatch_auto_petrol` using a simplified `2013/2015/2018` anchor set while evidence alignment is still being verified.
- Added a governed manual/provisional Ascent Sport hatch curve for `toyota_corolla_ascent-sport_zre182r_hatch_auto_petrol` using a `2014/2016/2018` anchor set while evidence alignment is still being verified.
- Added a durable memory decision that a curve is only complete when the anchor grid is resolved and the tag is aligned with the intended Autotrader and sold/Grays evidence lanes.

## 2026-03-21
- Removed the remaining Corolla ascent-sport year-reversal points from `CSV_data/restricted/curves.csv` so the governed curve set is monotonic across anchor years as well as kilometres.
- Added a non-mutating readiness smoke (`scripts/readiness_smoke.py`) plus dashboard CSV loader hardening so runtime pages load governed CSVs with stable mixed-type handling.
- Extended governance so new curve versions cannot introduce extra monotonicity issues relative to the latest versioned snapshot.

## 2026-03-16
- Renamed the live Mazda 3 BL shared curve base from `mazda_3_2.0_petrol_auto_hatch_bl` to `mazda_3_neo_petrol_auto_hatch_bl`, while keeping the old `2.0` tag as a backward-compatible alias.
- Standardized the Mazda 3 BL Maxx Sport canonical tag to `mazda_3_maxx-sport_petrol_auto_hatch_bl` and removed the legacy `bl10f1` alias tags from live curve resolution.
- Standardized the Mazda 3 BL Neo Sport canonical tag to `mazda_3_neo-sport_petrol_auto_hatch_bl` so Mazda trim tags consistently use hyphenated sport naming.

## 2026-03-15
- Added first-class curve aliases so multiple canonical trim tags can resolve to a single valuation curve without duplicating curve rows.
- Consolidated Mazda 3 BL 2.0 petrol auto hatch valuation into one shared base curve, with Neo, Neo Sport, Maxx, Maxx Sport, and Touring tags resolving through aliases.

## 2026-03-13
- Added governed dataset checks for exact schema contracts, curve integrity, and CI dataset delta enforcement via `scripts/governance_checks.py`.
- Added curve coverage reporting for dashboards and CI artifacts, with the current baseline reporting full coverage across observed canonical tags.
- Started versioned curve snapshots under `CSV_data/restricted/versions/curves_manifest.csv` and `CSV_data/restricted/versions/curves_20260313T093058Z.csv`.
- Corrected the `toyota_corolla_ascent_petrol_auto_sedan_zre172r` 2019 curve so the 60,000 km price point no longer drifts upward versus the 30,000 km anchor.
