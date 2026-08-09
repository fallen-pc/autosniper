# Auction Price Correction Model — Validation Report
Generated: 2026-06-28 12:49

## Training Configuration
| Parameter | Value |
|---|---|
| Training rows | 1,135 |
| Validation rows (holdout) | 284 |
| Feature count | 58 |
| Clip range | 0.4 – 2.0 |
| Upper model alpha | 0.92 |
| Median actual ratio (valid) | 1.060 |

## Q50 Model — Price Prediction Accuracy
| Metric | Value |
|---|---|
| MAE | $985 |
| RMSE | $1,492 |
| WAPE | 14.7% |

## Q50 Model — Error Distribution
| Percentile | Absolute Error |
|---|---|
| p50 (median error) | $631 |
| p75 | $1,259 |
| p90 | $2,223 |
| p99 | $5,746 |

## Q50 Model — Coverage by Tolerance
| Tolerance | % of predictions within |
|---|---|
| ±$500 | 44.0% |
| ±$1,000 | 66.5% |
| ±$2,000 | 86.6% |

## Upper Model (alpha=0.92) — Calibration
| Metric | Value | Target |
|---|---|---|
| Raw coverage (no calibration) | 78.9% | |
| Calibration multiplier | 1.1849 | 1.0 ideally |
| Calibrated coverage | 91.9% | >=92% |
| Status | FAIL - still under-covers after calibration, check for extreme ratio outliers in validation set | |

The calibration multiplier is applied to q90 price predictions at inference time.
A multiplier far from 1.0 (e.g. > 1.15 or < 0.90) means the base model is
systematically biased - investigate comps engine quality for the affected vehicles.

## Validation Set — Actual Ratio Distribution
(ratio = actual_auction_price / comps_p50 baseline)
| Percentile | Ratio |
|---|---|
| p10 | 0.694 |
| p50 | 1.060 |
| p90 | 1.686 |

## Next Steps
- If MAE > $1,500 or WAPE > 20%: review comps engine quality or add more training data.
- If upper model coverage < alpha target: rerun with --q90-alpha 0.94 or 0.95.
- If p99 error > $10,000: check for rows with very low comps_count leaking through
  (rerun with --min-comps 5).
- When satisfied: copy .cbm files and feature_names.json to artifacts/ to promote.
