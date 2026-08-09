# Sold Ledger Recovery - 2026-07-15

Recovered the no-date sold-history issue without weakening the strict sold dataset contract.

- `CSV_data/scrapers/sold_cars.csv` remains strict/model-ready runtime data and is skip-worktree locally.
- `scripts/build_sold_cars_all_ledger.py` builds `CSV_data/scrapers/sold_cars_all.csv` as the complete sold ledger, preserving historical sold rows that are not strict-ready.
- `scripts/recover_no_date_sold_from_artifacts.py` recovers missing `date_sold` values only from local sold-history artifacts with explicit sold-date columns, then promotes only rows that pass `validate_sold_cars_df`.
- The 2026-07-15 live run recovered 160 historical no-date rows from sold artifacts, promoted 154 to strict sold history, and left 6 in the ledger because odometer quality still failed strict validation.
- After recovery, strict sold history had 19,935 rows, zero blank `date_sold`, and zero duplicate URLs. Remaining ledger-only exclusions were 898 `[NO_DATE_SOLD]`, 453 `[BAD_YEAR]`, 221 `missing_odometer`, and 23 `[BAD_VIN]`.

Future checks should inspect `CSV_data/model_audit/sold_cars_all_ledger_exclusions.csv` after rebuilding the ledger. Do not use model-audit `purchase_date` as a sold-date substitute unless direct sale-date evidence is added.
