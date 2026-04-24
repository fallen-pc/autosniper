# Changelog

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
