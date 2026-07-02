# Telegram alert status - 2026-07-03

## Status
- Telegram delivery is working.
- Candidate alerts remain driven by stored AI Analysis output, not separate alert logic.
- Daily status summaries now use clearer wording for no-Buy, no-current-AI-row, and current active AI row cases.

## Fix
- Dropped-coverage active listings now write explicit AI Analysis labels:
  - `action_label = Review`
  - `bid_status = Not covered`
  - `hard_max_safety = No coverage`
  - `verdict = Not Covered`
- This prevents daily Telegram summaries from showing blank action rows when current active listings are no longer curve-covered.

## Verification
- `venv\Scripts\python.exe -m pytest tests\test_active_monitor.py tests\test_scheduled_jobs.py tests\test_ai_listing_valuation.py tests\test_decision_policy.py`
- Result: `71 passed`
