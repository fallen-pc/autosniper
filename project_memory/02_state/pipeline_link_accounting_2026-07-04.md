# Pipeline Link Accounting - 2026-07-04

## Summary

Audited link collection through downstream materialization. All collected URLs were accounted for, but two lifecycle hygiene gaps were fixed:

- `scripts/update_master.py` now prunes `active_vehicle_links.csv` from terminal `vehicle_state` rows, not only rows already written to sold/referred CSVs.
- Sold materialization now uses `normalised_data.csv` as an identity fallback when `vehicle_static_details.csv` has been pruned to the active queue.

Sold date parsing was also hardened so ISO `YYYY-MM-DD` values are preserved and Australian `AEST`/`AEDT` date strings parse consistently.

## Verification

- `venv\Scripts\python.exe -m pytest tests\test_update_master_snapshot.py tests\test_sold_date_normalization.py -q`
- Result: `17 passed`

Runtime verification after rerunning `scripts/update_master.py`:

- `sold_cars.csv`: `18,470` rows
- `active_vehicle_links.csv`: `264` rows
- terminal state URLs still in active links: `0`
- active links missing static rows: `0`
