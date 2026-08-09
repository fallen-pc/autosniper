# Active master cleanup - 2026-07-03

## Status
- Active materialization now filters out rows without current live signals before writing `active_vehicle_details.csv`.
- Dead URLs from `vehicle_state.csv` are pruned from `active_vehicle_links.csv` alongside sold/referred rows.
- Canonical eligibility now treats lowercase `[ok]` the same as `[OK]`.

## Verification
- `venv\Scripts\python.exe -m pytest tests\test_update_master_snapshot.py tests\test_canonical_tagging_cache.py`
- Result: `17 passed`
