# Comps time-decay, regression constants, confidence calibration — 2026-08-29

## Task #3: Time-decay weighting in CompsEngine

Added `decay_halflife_days=365` to `CompsEngineConfig`.  `_decay_weights()` computes
`exp(-ln(2)/halflife * days_old)` for each comp relative to the subject's sale date.
`_weighted_percentile()` replaces the plain numpy `percentile` call when computing
`p50`/`p90` in `predict_row()`.  Setting `decay_halflife_days=0` disables decay (flat
weights), which is the same as the old behaviour and used for comparison in tests.

## Task #4: Regression-derived adjustment constants

`fit_adjustment_constants(data, config=None)` in `shared/comps_engine.py` runs OLS
(`np.linalg.lstsq`) over the sold data:

    sale_price ~ intercept + year + odometer_per_10k + repair_severity + cross_state

Returns a new `CompsEngineConfig` with the four coefficients replacing the gut-feel
defaults ($700/yr, $280/10k, $80/pt, $200 state).  Coefficients are clamped to sane
ranges to prevent thin-dataset nonsense.  Falls back to the base config unchanged when
fewer than 30 rows are available.

Wired into `scripts/prepare_sold_training_data.py`: the training dataset is now built
with fitted rather than hardcoded constants.  Constants are printed at runtime so they
can be observed and compared across dataset versions.

## Task #7: Confidence calibration script + page section

`scripts/calibrate_confidence.py` — runs offline against `sold_cars.csv`:
1. Computes `comps_p50` via `CompsEngine` with fitted constants
2. Runs batch CatBoost inference (via the same models loaded by the live pipeline)
3. Computes MAE / MdAE / MAPE and q90 coverage overall and by q90−q50 spread bucket
4. Writes `artifacts/confidence_calibration.json`

`pages/17_MODEL_PROOF.py` — new "CatBoost Confidence Calibration" section renders the
JSON when it exists, showing overall metrics and a per-bucket table.  Shows an info
notice with the run command when the file is absent.

Key design: spread bucket analysis lets us see whether a wide q90−q50 band genuinely
predicts higher error — if it does, spread is a valid uncertainty signal and the current
confidence formula can be tightened.  The q90 coverage metric tells us whether the
calibration multiplier in `correction_model_metrics.json` needs adjusting.
