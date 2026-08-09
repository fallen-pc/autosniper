# Telegram Alert Test Coverage - 2026-07-15

Added direct unit coverage for `shared/telegram_alerts.py`, which previously was mostly exercised indirectly through callers that mocked the alert helpers.

Covered behaviours:

- `send_once()` records a successful alert in the alert log and suppresses duplicate alert type + URL sends.
- `send_on_state_change()` persists the latest state, suppresses unchanged state repeats, and allows changed-state notifications.
- Disabled Telegram credentials short-circuit without sending or writing runtime CSV files.

Verification:

- `venv\Scripts\python.exe -m pytest tests\test_telegram_alerts.py -q` -> `3 passed`
- `venv\Scripts\python.exe -m pytest tests\test_telegram_alerts.py tests\test_ai_listing_valuation.py tests\test_scheduled_jobs.py -q` -> `62 passed`
- `venv\Scripts\python.exe -m pytest -q` -> `486 passed, 2 warnings`
