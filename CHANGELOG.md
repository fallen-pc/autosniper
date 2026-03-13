# Changelog

## 2026-03-13
- Added governed dataset checks for exact schema contracts, curve integrity, and CI dataset delta enforcement via `scripts/governance_checks.py`.
- Added curve coverage reporting for dashboards and CI artifacts, with the current baseline reporting full coverage across observed canonical tags.
- Started versioned curve snapshots under `CSV_data/restricted/versions/curves_manifest.csv` and `CSV_data/restricted/versions/curves_20260313T093058Z.csv`.
- Corrected the `toyota_corolla_ascent_petrol_auto_sedan_zre172r` 2019 curve so the 60,000 km price point no longer drifts upward versus the 30,000 km anchor.
