# Comps time-decay weighting — 2026-08-29

## Current state

CompsEngine retains exponential time-decay weighting for comparable sales.
decay_halflife_days=365 is configurable, and setting it to 0 restores flat
weights. Focused tests compare decayed and unweighted medians.

## Reversal on 2026-08-30

The regression-derived adjustment constants and full-history CatBoost confidence
calibration were removed before publication. They did not match the recommended
aligned model pipeline or its repair-enriched feature inputs, and the regression
coefficient mapping was invalid.

The Model Proof calibration section and scripts/calibrate_confidence.py were also
removed. Any future calibration must use a fresh, model-consistent holdout with
matched model, metrics, predictions, baseline, and repair features.
