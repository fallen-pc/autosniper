# Carsales Curve Batch - 2026-07-04

Built four governed resale curves from July 2026 private Carsales/Apify staging evidence:

- `toyota_aurion_at-x_gsv40r_sedan_auto_petrol`
- `holden_calais_ve_sedan_auto_petrol`
- `kia_cerato_s_yd_sedan_auto_petrol`
- `holden_cruze_cdx_jg_sedan_auto_petrol`

The matching rows were added to `config/allowed_variants.csv`, `config/curve_groups_v2.csv`,
`config/supported_curve_universe_v1.csv`, and `config/curve_anchor_overrides_v2.csv`.
The batch intentionally excluded thinner or volatile lanes from the same scrape, including
Ford Falcon FG MkII XR6, Holden Calais V, Holden Barina CDX, and Toyota Aurion Sportivo.

Verification:

- `venv\Scripts\python.exe -m pytest tests\test_canonical_tagging_carsales_batch.py tests\test_curve_groups_v2.py tests\test_ops_utils_curve_meta.py -q`
- `venv\Scripts\python.exe scripts\build_restricted_datasets.py`
- `venv\Scripts\python.exe scripts\update_master.py`
- `venv\Scripts\python.exe governance\run_checks.py coverage-report`
- `venv\Scripts\python.exe governance\run_checks.py check --skip-dataset-delta`
- `venv\Scripts\python.exe scripts\curve_validator.py --curves CSV_data\restricted\curves.csv`
- `venv\Scripts\python.exe governance\run_checks.py snapshot-curves`
- `venv\Scripts\python.exe scripts\readiness_smoke.py`

Post-build active coverage moved from 22 to 26 restricted active rows. The four newly covered
live rows are the current Aurion AT-X, plain Calais VE, Cerato YD S, and Cruze JG CDX rows.
