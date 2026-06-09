# Ford/Mitsubishi Curve Expansion

2026-06-09: Added governed curve coverage for Ford Territory SZ diesel automatic SUV, Mitsubishi Pajero GLX NT/NW diesel automatic SUV, and Mitsubishi Triton GLX MN diesel manual ute.

Scope:
- Added narrow allowed-variant and curve-group mappings for the Ford/Mitsubishi lanes.
- Extended canonical tagging to recognize Ford/Mitsubishi makes, target models, and SZ/NT/NW/MN/MQ short series codes.
- Added focused canonical-tagging tests to keep Ford Territory petrol/manual, Pajero non-GLX/petrol, and Triton GLX-R/auto/MQ rows out.
- Recorded Ford, Mitsubishi, and shared high-km extension curve decisions.

Verification:
- `venv\Scripts\python.exe -m pytest tests/test_canonical_tagging_ford.py tests/test_canonical_tagging_mitsubishi.py tests/test_ai_listing_valuation.py tests/test_decision_policy.py -q` passed with 30 tests.
- `python governance\run_checks.py coverage-report` reported 56/56 observed tags covered and 0 monotonicity issues.
- `git diff --check` was clean after generated curve CSV line endings were normalized.
