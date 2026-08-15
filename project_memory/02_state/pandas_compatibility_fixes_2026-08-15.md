# Pandas and local model compatibility fixes - 2026-08-15

- `shared/repair_pricing_schedule.py` now casts quote price columns to object dtype before assigning parsed integer values, preserving numeric quote values under pandas 3 Arrow-string behavior.
- `scripts/update_master.py` now normalizes static VIN fallback values to uppercase text before blank and sentinel checks, preventing missing `NaN` values from receiving string methods.
- The project-declared `catboost==1.2.10` dependency was installed into `.venv_local` so auction-model inference tests execute locally.
- Verification: the four original failures passed, the affected regression suites passed (`60`), and the complete `tests/` tree passed (`946 passed, 1 xfailed`).
