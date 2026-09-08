# Local repair ledger automatic refresh - 2026-09-09

- The VPS remains the authority for scraper outputs and the live repair-review queue.
- `scripts/refresh_local_repair_ledgers.py` pulls only those runtime-owned inputs, validates every download before installing any of them, and atomically replaces changed local copies.
- Locally authored `repair_review_decisions.csv`, `repair_pricing_schedule.csv`, and `repair_quote_requests.csv` are deliberately never pulled from the VPS or overwritten.
- Derived Repair Review outputs and the full Repair Pricing matrix rebuild only when an input is newer or an output is missing.
- `AutoSniper Local Repair Ledger Refresh` is registered in Windows Task Scheduler for 13:00 daily, after the normal VPS daily pipeline window, with missed-start recovery and retry enabled.
- Live proof on 2026-09-09 refreshed 30,802 condition rows into 18,810 deduplicated repair lines and rebuilt the 285-cell pricing matrix from 22,429 sold listings. A subsequent Task Scheduler run skipped both current outputs and exited `0`.
- Focused validation: `46 passed` across refresh, workbench, pricing-schedule, and repair-extraction tests; Ruff and Python compilation passed.
