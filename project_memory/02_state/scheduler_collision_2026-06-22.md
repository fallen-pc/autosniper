# Scheduler Collision Fix - 2026-06-22

The June 21/22 scheduler collision was not a task registration regression. The registered Windows tasks still run daily at 09:00 and hourly at :13 past the hour.

The recurring failure was in missed-daily catch-up state handling: after the grace window, hourly could decide daily coverage was missing while an active daily lock already covered the target local date. A lock-busy daily attempt could then overwrite `status/daily_run_state.json` as skipped even though a daily run was still active.

`scripts/scheduled_jobs.py` now treats an active non-stale daily lock for the target local date as daily coverage in progress. Catch-up stands down in that case, and lock-busy daily attempts do not overwrite the running daily state. Regression tests in `tests/test_scheduled_jobs.py` cover active daily, stale daily, overwritten skipped state, and lock-busy daily behavior.
