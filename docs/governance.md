# Governance

## Controls
- Exact schema contracts are enforced for the governed CSV datasets.
- Restricted curves must stay in canonical-tag format, keep `price_low <= price_mid <= price_high`, and not increase as `km_bucket` rises within an anchor year.
- Curve coverage is reported from `vehicle_static_details.csv` plus `restricted_group_map.csv` so missing canonical curves are visible in CI and the Curves page.
- Tracked dataset changes are blocked in CI unless explicitly allowlisted or accompanied by the required curve versioning artifacts.

## Commands
```powershell
python scripts/governance_checks.py check
python scripts/governance_checks.py coverage-report
python scripts/governance_checks.py snapshot-curves --note "Describe the curve update"
python scripts/readiness_smoke.py
```

## Curve Versioning
- `shared.curves.save_curves()` now snapshots `CSV_data/restricted/curves.csv` into `CSV_data/restricted/versions/`.
- Curve Builder V2 is the supported operator path for new/refresh curve pricing, using Carsales/Apify or manual Carsales evidence.
- `scripts/generate_curve_candidates.py` may still be used to prioritize lanes for review, but it does not set retail curve prices.
- `scripts/process_curve_candidates.py` is a disabled legacy AI curve writer; Autotrader remains comparison/scrape follow-up only.
- Every committed `curves.csv` change must include:
  - `CSV_data/restricted/versions/curves_<version>.csv`
  - `CSV_data/restricted/versions/curves_manifest.csv`
  - `CHANGELOG.md`
- Governance also compares the current monotonicity report to the latest prior versioned snapshot and fails on any new monotonicity issue, even if it is only a warning.

## Naming Rules
- New source files under `scripts/`, `shared/`, and `docs/` should use lowercase snake_case names.
- Do not add active-source files with `backup`, `copy`, `tmp`, `temp`, `old`, or `final` in the stem.
- Move superseded helpers into an archive directory instead of keeping parallel legacy variants beside active scripts.

## CI
- GitHub Actions runs the governed checks in `.github/workflows/governance.yml`.
- The workflow writes curve coverage artifacts into `output/governance/` and publishes the markdown summary into the job summary.
- Set `AUTOSNIPER_EXPECTED_DATASET_CHANGES` only for intentional tracked dataset updates that are not curve-versioned changes.
