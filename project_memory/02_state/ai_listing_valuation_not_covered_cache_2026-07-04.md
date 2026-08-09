# AI listing valuation not-covered cache rows - 2026-07-04

## Status

- Active AI valuation rows now keep operator-facing identity fields when a listing falls out of curve coverage.
- `ops.active_monitor._upsert_not_covered_result` writes `year`, `make`, `model`, `variant`, `location`, and a deterministic `valuation_input_hash` for synthesized `Review / Not Covered` active rows.
- The local runtime cache `CSV_data/ai/ai_listing_valuations.csv` was cleaned so stale `test://` rows are gone and the current active `Not Covered` rows have identity/hash fields backfilled from `active_vehicle_details.csv`.
- The runtime cache remains `skip-worktree`, so source commits should carry the writer/test fix while local runtime data changes stay out of normal source commits.

## Verification

- `venv\Scripts\python.exe -m pytest tests\test_active_monitor.py tests\test_ai_listing_valuation.py tests\test_update_master_snapshot.py tests\test_sold_date_normalization.py -q`
- Result: `54 passed`
- `venv\Scripts\python.exe scripts\project_memory.py check`
- Result: passed
- `venv\Scripts\python.exe scripts\governance_checks.py check`
- Result: passed
- Current local `CSV_data/ai/ai_listing_valuations.csv`: `179` rows, `0` `test://` rows, `22` active rows, and `0.0%` blanks across active `year/make/model/variant/location/valuation_input_hash/current_bid/current_bid_numeric/action_label/bid_status`.
