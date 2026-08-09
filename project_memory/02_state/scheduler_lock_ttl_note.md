# Scheduler Lock TTL Note

- 2026-05-27: The daily/hourly lock fix is preserved in source. `scripts/scheduled_jobs.py` now checks the TTL for the job that owns an existing `logs/scrape.lock`, so a shorter hourly monitor run cannot expire a still-valid daily lock. Regression coverage lives in `tests/test_scheduled_jobs.py::test_hourly_does_not_expire_active_daily_lock`.
