"""Calibrate CatBoost confidence signals against historical close prices.

For every sold listing where CatBoost can produce q50/q90 predictions:
  - Compute absolute error:  |q50_pred - actual_close|
  - Bucket by spread:        (q90_pred - q50_pred) / q50_pred
  - Report:
      * MAE and MdAE at each spread bucket
      * Calibration: actual_price <= q90_pred  (should be ~90%)
      * MAPE (mean absolute percentage error) overall and by bucket

Output: artifacts/confidence_calibration.json

The script can run standalone:
    python scripts/calibrate_confidence.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.comps_engine import CompsEngine, CompsEngineConfig, fit_adjustment_constants
from shared.data_loader import dataset_path

logger = logging.getLogger(__name__)

DEFAULT_SOLD_PATH = dataset_path("sold_cars.csv")
DEFAULT_OUTPUT_PATH = Path("artifacts/confidence_calibration.json")
SPREAD_BUCKET_EDGES = [0.0, 0.05, 0.10, 0.20, 0.35, float("inf")]
SPREAD_BUCKET_LABELS = ["<5%", "5-10%", "10-20%", "20-35%", ">35%"]
MIN_COMPS_FOR_PREDICTION = 3


def _load_models():
    try:
        from catboost import CatBoostRegressor, Pool
        return CatBoostRegressor, Pool
    except ImportError:
        return None, None


def _compute_comps(df: pd.DataFrame) -> pd.DataFrame:
    """Add comps_p50 / comps_count columns via CompsEngine with fitted constants."""
    config = fit_adjustment_constants(df)
    engine = CompsEngine(df, config)
    comps = engine.run()
    return pd.concat([df.reset_index(drop=True), comps], axis=1)


def _batch_predict(df: pd.DataFrame, CatBoostRegressor, Pool) -> pd.DataFrame:
    """Run CatBoost q50/q90 inference on all rows with a valid comps_p50."""
    from shared.auction_model import _try_load_models, _q50_model, _q90_model, _feature_names
    import shared.auction_model as _am

    if not _try_load_models():
        raise RuntimeError("CatBoost models not available — check artifacts/ directory.")

    q50_model = _am._q50_model
    q90_model = _am._q90_model
    feature_names = _am._feature_names
    calibration_multiplier = _am._calibration_multiplier or 1.0
    q90_fallback_multiplier = _am._q90_fallback_multiplier or 1.3243

    valid = df[
        df["comps_p50"].notna() & (df["comps_p50"] > 0) & (df["comps_count"] >= MIN_COMPS_FOR_PREDICTION)
    ].copy()

    if valid.empty:
        return pd.DataFrame()

    from shared.auction_model import _build_feature_row, _str_or_unknown

    rows_dicts = []
    for _, row in valid.iterrows():
        feat = _build_feature_row(
            row.to_dict(),
            comps_p50=float(row["comps_p50"]),
            curve_tag=str(row.get("curve_tag") or "UNKNOWN"),
            repair_tags=str(row.get("repair_tags") or "[]"),
            repair_severity=float(row.get("repair_severity") or 0.0),
            decision_condition_only=str(row.get("general_condition") or "UNKNOWN"),
            estimated_parts_cost_aud=0.0,
            repair_tag_flags={},
            total_repair_tags=0,
        )
        rows_dicts.append(feat)

    feat_df = pd.DataFrame(rows_dicts)

    cat_indices = [i for i, n in enumerate(feature_names) if feat_df[n].dtype == object]
    pool = Pool(
        data=feat_df[feature_names],
        feature_names=feature_names,
        cat_features=cat_indices,
    )

    q50_ratios = q50_model.predict(pool)
    q90_ratios = q90_model.predict(pool)
    comps_arr = valid["comps_p50"].to_numpy(dtype=float)

    q50_prices = q50_ratios * comps_arr
    q90_prices_raw = q90_ratios * comps_arr
    q90_prices = np.where(q90_prices_raw < q50_prices, q50_prices * q90_fallback_multiplier, q90_prices_raw)
    q90_prices = q90_prices * calibration_multiplier

    valid = valid.copy()
    valid["pred_q50"] = q50_prices
    valid["pred_q90"] = q90_prices
    return valid


def calibrate(sold_path: Path, output_path: Path) -> dict:
    df = pd.read_csv(sold_path, low_memory=False)
    df = df.dropna(subset=["price_numeric"])
    df["price_numeric"] = pd.to_numeric(df["price_numeric"], errors="coerce")
    df = df[df["price_numeric"] > 500].copy()

    CatBoostRegressor, Pool = _load_models()
    if CatBoostRegressor is None:
        raise RuntimeError("catboost package not installed.")

    print(f"[calibrate] computing comps for {len(df):,} rows …")
    df = _compute_comps(df)

    print(f"[calibrate] running CatBoost inference …")
    results = _batch_predict(df, CatBoostRegressor, Pool)
    if results.empty:
        raise ValueError("No rows had enough comps for prediction — check data.")

    actual = results["price_numeric"].to_numpy(dtype=float)
    q50 = results["pred_q50"].to_numpy(dtype=float)
    q90 = results["pred_q90"].to_numpy(dtype=float)

    abs_err = np.abs(q50 - actual)
    pct_err = abs_err / actual * 100
    spread = (q90 - q50) / q50.clip(min=1)
    bucket_idx = np.digitize(spread, SPREAD_BUCKET_EDGES[1:-1])

    bucket_stats = []
    for i, label in enumerate(SPREAD_BUCKET_LABELS):
        mask = bucket_idx == i
        if not mask.any():
            bucket_stats.append({"spread_bucket": label, "n": 0})
            continue
        bucket_stats.append(
            {
                "spread_bucket": label,
                "n": int(mask.sum()),
                "mae": round(float(np.mean(abs_err[mask])), 0),
                "mdae": round(float(np.median(abs_err[mask])), 0),
                "mape_pct": round(float(np.mean(pct_err[mask])), 1),
                "q90_coverage_pct": round(float((actual[mask] <= q90[mask]).mean() * 100), 1),
            }
        )

    overall = {
        "n_rows_with_prediction": int(len(results)),
        "n_rows_total": int(len(df)),
        "mae": round(float(np.mean(abs_err)), 0),
        "mdae": round(float(np.median(abs_err)), 0),
        "mape_pct": round(float(np.mean(pct_err)), 1),
        "q90_coverage_pct": round(float((actual <= q90).mean() * 100), 1),
        "by_spread_bucket": bucket_stats,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(overall, fh, indent=2)

    print(
        f"[calibrate] n={overall['n_rows_with_prediction']} "
        f"MAE=${overall['mae']:,.0f} MdAE=${overall['mdae']:,.0f} "
        f"MAPE={overall['mape_pct']}% q90_cov={overall['q90_coverage_pct']}%"
    )
    print(json.dumps({"by_bucket": bucket_stats}, indent=2))
    return overall


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate CatBoost confidence signals.")
    parser.add_argument("--sold", type=Path, default=DEFAULT_SOLD_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)
    calibrate(args.sold, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
