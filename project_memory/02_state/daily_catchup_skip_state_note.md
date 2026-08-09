# Daily catch-up skip state note

2026-05-30: `scripts/scheduled_jobs.py` now bases missed-daily catch-up eligibility on the last successful coverage date, not the last attempted coverage date. A daily or catch-up attempt that cannot acquire `logs/scrape.lock` records `last_status: skipped` with the lock-busy reason while preserving the previous successful coverage fields, so a stale `running` state cannot block the next catch-up.
