# Staged Curve Conversion - 2026-07-12

Converted four already-scraped Carsales staging lanes into governed resale curves:

- `holden_cruze_cdx_jh-series-ii_sedan_auto_petrol`
- `holden_cruze_cd_jh-series-ii_sedan_auto_petrol`
- `hyundai_elantra_active_md3_sedan_auto_petrol`
- `hyundai_elantra_active_ad_sedan_auto_petrol`

The batch deliberately skipped weaker staged lanes where the fitted grid was too flat,
thin, or not aligned with live rows, including older Corolla ZZE122R hatch trims and
thin Kluger/Golf/Outlander adjacent trims.

Verification:

- `venv\Scripts\python.exe -m pytest tests\test_canonical_tagging_carsales_batch.py tests\test_curve_groups_v2.py tests\test_ops_utils_curve_meta.py -q`
- `venv\Scripts\python.exe scripts\build_restricted_datasets.py`
- `venv\Scripts\python.exe scripts\update_master.py`
- `venv\Scripts\python.exe governance\run_checks.py coverage-report`
- `venv\Scripts\python.exe governance\run_checks.py check --skip-dataset-delta`
- `venv\Scripts\python.exe scripts\curve_validator.py --curves CSV_data\restricted\curves.csv`
- `venv\Scripts\python.exe governance\run_checks.py snapshot-curves`
- `venv\Scripts\python.exe scripts\readiness_smoke.py`

Post-build restricted active coverage moved from 51 to 55 rows. The four newly covered
live rows are the current 2012 Cruze CD, 2012 Cruze CDX, 2015 Elantra Active MD3, and
2018 Elantra Active AD rows.
