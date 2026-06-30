# Pipeline Sync Audit — 2026-07-01

## What changed

Cross-pipeline consistency audit and cleanup across shared modules, scripts, and tests.

### Bugs fixed

1. **`shared/repair_features.py`** — removed duplicate `"oil leak"` keyword in `engine_mechanical` category.

2. **`shared/repair_pricing.py`** — `hail_damage` cost now looks up its own key in `V2_REPLACEMENT_COSTS` instead of always using `"structural_damage"` key (both $900 today, but semantically correct and future-safe).

3. **`shared/missed_opportunities.py`** — `compute_decision_metrics` now forwards `comps_count` as `expected_auction_comps_count` to `derive_action_label_from_row`, so the historical replay applies the same `MIN_COMPS_FOR_BUY = 3` gate as the live AI Analysis page.

### Simplifications

4. **`shared/missed_opportunities.py`** — extracted magic `3000` profit threshold into `STRONG_FLIP_PROFIT_THRESHOLD = 3_000` constant with explanatory comment distinguishing it from `MIN_NET_PROFIT_ABSOLUTE`.

5. **`shared/canonical_tagging.py`** — `assign_canonical_tag` return type simplified from `Tuple[str, str, str]` to `Tuple[str, str]`. The third element `drivetrain_source` was always `""` and discarded by every caller. All return statements, the internal `tag_dataframe` caller, and the dead comment removed.

6. **`scripts/extract_vehicle_details.py`, `scripts/update_bids.py`, `scripts/update_master.py`** — removed defensive `drop(columns=["drivetrain_source"])` guards that existed only to strip the now-removed third return value.

7. **7 test files** — updated `tag, reason, _drivetrain = assign_canonical_tag(...)` calls to `tag, reason = assign_canonical_tag(...)`.

### Confirmed non-issues (false positives from audit)

- Hail classified as "structural" in `DEFECT_PATTERNS` is consistent with `repair_pricing.py` line 570 (hail_damage → structural treatment). Not a bug.
- `ENGINE_DEFECT_PATTERN` is identical in `build_aligned_training_table.py` and `6_AI_ANALYSIS.py`. Not a bug.
- Carsales missing `general_condition` does not matter — Carsales data never enters the repair-assessment or AI Analysis path.
- `REFERRED_LISTING_SCHEMA` is used by `governance.py` DatasetContract — not dead code.
