# Changelog

## 2026-04-10
- Split the Toyota Corolla `zre182r` hatch family by trim in the supported curve universe and V2 group mapping so `ascent` and `ascent-sport` no longer share one base curve.
- Added a governed manual/provisional Ascent hatch curve for `toyota_corolla_ascent_zre182r_hatch_auto_petrol` using a simplified `2013/2015/2018` anchor set while evidence alignment is still being verified.
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
