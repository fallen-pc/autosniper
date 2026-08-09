---
date: 2026-06-29
topic: CatBoost auction price model (v3) integrated into live pipeline
status: complete
---

## What changed

Wired CatBoost quantile regression into `scripts/ai_listing_valuation.py`:

- `shared/auction_model.py`: lazy-loading inference wrapper; predicts q50 (median) and q90 (upper bound) auction prices; crossing guard prevents q90 < q50 using a fallback multiplier (1.3243 = 92nd percentile of actual/q50 on validation set).
- Priority: catboost → comps_median → resale_discount fallback.
- v3 model: trained on 1135 rows, MAE $985, WAPE 14.7%, calibrated coverage 91.9%.
- `.cbm` binary artifacts excluded from git (regenerate via `scripts/rebuild_auction_model.py --aligned`).
- `artifacts/correction_model_metrics.json` and `artifacts/feature_names.json` tracked in git.

## Key implementation notes

- CatBoost requires a `Pool` object with explicit `cat_features` indices for inference.
- Float features (`year`, `odometer_reading`, `bids`, `no_of_seats`, `no_of_cylinders`, `engine_capacity`) must be passed as numeric, not strings.
- Quantile crossing (~10% of cases, sparse feature regions) handled by crossing guard using `q90_fallback_multiplier` stored in `correction_model_metrics.json`.
