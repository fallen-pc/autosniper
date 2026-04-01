"""Train ratio-based auction close-price correction models (q50 + q90)."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool

from scripts.atomic_csv import write_dataframe_csv_atomic

DATE_CANDIDATES = [
    "sold_date",
    "sale_date",
    "auction_end",
    "end_date",
    "date_sold",
    "sold_at",
    "ended_at",
]
PRICE_CANDIDATES = [
    "final_price",
    "sold_price",
    "price",
    "hammer_price",
    "winning_bid",
    "sale_price",
]
BASELINE_CANDIDATES = [
    "baseline_price",
    "comps_p50",
    "comps_price_p50",
    "comps_median",
    "comps_mid",
    "baseline_estimate",
    "comps_estimate",
]
ID_CANDIDATES = ["url", "listing_url", "id", "row_id", "vehicle_id"]


@dataclass
class Cols:
    id_col: Optional[str]
    date_col: str
    price_col: str
    baseline_col: str


def _pick_first_existing(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def _coerce_numeric(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def _load_and_detect_cols(path: str) -> Tuple[pd.DataFrame, Cols]:
    df = pd.read_csv(path)

    date_col = _pick_first_existing(df, DATE_CANDIDATES)
    if not date_col:
        raise ValueError(f"Missing date column. Tried: {DATE_CANDIDATES}")

    price_col = _pick_first_existing(df, PRICE_CANDIDATES)
    if not price_col:
        raise ValueError(f"Missing actual price column. Tried: {PRICE_CANDIDATES}")

    baseline_col = _pick_first_existing(df, BASELINE_CANDIDATES)
    if not baseline_col:
        raise ValueError(f"Missing baseline price column. Tried: {BASELINE_CANDIDATES}")

    id_col = _pick_first_existing(df, ID_CANDIDATES)

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", utc=True).dt.tz_convert(None)
    df[price_col] = _coerce_numeric(df[price_col])
    df[baseline_col] = _coerce_numeric(df[baseline_col])

    return df, Cols(id_col=id_col, date_col=date_col, price_col=price_col, baseline_col=baseline_col)


def _time_split(df: pd.DataFrame, date_col: str, validation_days: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    df = df.dropna(subset=[date_col]).copy()
    if df.empty:
        raise ValueError("No rows remain after dropping missing date values.")
    cutoff = df[date_col].max() - pd.Timedelta(days=int(validation_days))
    train = df[df[date_col] < cutoff].copy()
    valid = df[df[date_col] >= cutoff].copy()
    if train.empty or valid.empty:
        raise ValueError(
            f"Time split produced empty partition(s): train={len(train)}, valid={len(valid)}, "
            f"validation_days={validation_days}."
        )
    return train, valid


def _build_feature_frame(df: pd.DataFrame, cols: Cols, drop_cols: Optional[List[str]]) -> pd.DataFrame:
    X = df.copy()
    drop_cols = drop_cols or []
    if cols.price_col in X.columns:
        X.drop(columns=[cols.price_col], inplace=True)
    for column in drop_cols:
        if column in X.columns:
            X.drop(columns=[column], inplace=True)
    if cols.date_col in X.columns:
        dt = pd.to_datetime(df[cols.date_col], errors="coerce")
        X["sold_dow"] = dt.dt.dayofweek
        X["sold_month"] = dt.dt.month
        X["sold_year"] = dt.dt.year
        X.drop(columns=[cols.date_col], inplace=True, errors="ignore")
    for column in X.columns:
        if X[column].dtype == "object":
            X[column] = X[column].fillna("UNKNOWN").astype(str)
    return X


def _train_quantile(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_valid: pd.DataFrame,
    y_valid: np.ndarray,
    alpha: float,
    seed: int,
    iterations: int,
) -> CatBoostRegressor:
    cat_cols = [idx for idx, column in enumerate(X_train.columns) if X_train[column].dtype == "object"]
    train_pool = Pool(X_train, y_train, cat_features=cat_cols)
    valid_pool = Pool(X_valid, y_valid, cat_features=cat_cols)
    model = CatBoostRegressor(
        loss_function=f"Quantile:alpha={alpha}",
        depth=8,
        learning_rate=0.05,
        iterations=iterations,
        random_seed=seed,
        eval_metric="MAE",
        od_type="Iter",
        od_wait=80,
        verbose=200,
    )
    model.fit(train_pool, eval_set=valid_pool, use_best_model=True)
    return model


def _price_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    error = y_pred - y_true
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(error**2)))
    denom = float(np.sum(np.abs(y_true))) or 1.0
    wape = float(np.sum(np.abs(error)) / denom)
    return {"mae": mae, "rmse": rmse, "wape": wape}


def _prepare_model_datasets(
    df: pd.DataFrame,
    cols: Cols,
    validation_days: int,
    clip_low: float,
    clip_high: float,
    drop_cols: List[str],
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, np.ndarray, np.ndarray]:
    prepared_df = df.dropna(subset=[cols.price_col, cols.baseline_col]).copy()
    prepared_df = prepared_df[(prepared_df[cols.price_col] > 0) & (prepared_df[cols.baseline_col] > 0)].copy()
    prepared_df["auction_ratio"] = (prepared_df[cols.price_col] / prepared_df[cols.baseline_col]).clip(
        clip_low, clip_high
    )

    train_df, valid_df = _time_split(prepared_df, cols.date_col, validation_days)
    X_train = _build_feature_frame(train_df, cols, drop_cols)
    X_valid = _build_feature_frame(valid_df, cols, drop_cols)
    y_train = train_df["auction_ratio"].to_numpy(dtype=float)
    y_valid = valid_df["auction_ratio"].to_numpy(dtype=float)
    return prepared_df, train_df, valid_df, X_train, X_valid, y_train, y_valid


def main() -> None:
    parser = argparse.ArgumentParser(description="Train quantile ratio models for auction price correction.")
    parser.add_argument("--train-data", required=True, help="CSV containing sold rows + baseline comps price.")
    parser.add_argument("--validation-days", type=int, default=60, help="Holdout window based on date column.")
    parser.add_argument("--clip-low", type=float, default=0.70, help="Lower clamp for ratio target.")
    parser.add_argument("--clip-high", type=float, default=1.30, help="Upper clamp for ratio target.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", default="artifacts")
    parser.add_argument("--iterations", type=int, default=2500, help="Max iterations per quantile model.")
    parser.add_argument("--predictions-out", default=None)
    parser.add_argument("--metrics-out", default=None)
    parser.add_argument("--model-q50-out", default=None)
    parser.add_argument("--model-q90-out", default=None)
    parser.add_argument("--drop-cols", default="", help="Comma-separated columns to drop from features.")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    df, cols = _load_and_detect_cols(args.train_data)
    drop_cols = [c.strip() for c in args.drop_cols.split(",") if c.strip()]

    _, train_df, valid_df, X_train, X_valid, y_train, y_valid = _prepare_model_datasets(
        df=df,
        cols=cols,
        validation_days=args.validation_days,
        clip_low=args.clip_low,
        clip_high=args.clip_high,
        drop_cols=drop_cols,
    )

    model_q50 = _train_quantile(
        X_train, y_train, X_valid, y_valid, alpha=0.5, seed=args.seed, iterations=args.iterations
    )
    model_q90 = _train_quantile(
        X_train, y_train, X_valid, y_valid, alpha=0.9, seed=args.seed + 1, iterations=args.iterations
    )

    baseline_valid = valid_df[cols.baseline_col].to_numpy(dtype=float)
    actual_price = valid_df[cols.price_col].to_numpy(dtype=float)
    pred_ratio_q50 = model_q50.predict(X_valid).astype(float)
    pred_ratio_q90 = model_q90.predict(X_valid).astype(float)
    pred_price_q50 = baseline_valid * pred_ratio_q50
    pred_price_q90 = baseline_valid * pred_ratio_q90

    metrics = {
        "validation_days": args.validation_days,
        "rows_train": int(len(train_df)),
        "rows_valid": int(len(valid_df)),
        "clip_low": args.clip_low,
        "clip_high": args.clip_high,
        "price_metrics_q50": _price_metrics(actual_price, pred_price_q50),
        "coverage_p90": float(np.mean(actual_price <= pred_price_q90)),
        "columns": {
            "id_col": cols.id_col,
            "date_col": cols.date_col,
            "price_col": cols.price_col,
            "baseline_col": cols.baseline_col,
        },
    }

    model_q50_out = args.model_q50_out or os.path.join(args.out_dir, "auction_ratio_q50.cbm")
    model_q90_out = args.model_q90_out or os.path.join(args.out_dir, "auction_ratio_q90.cbm")
    model_q50.save_model(model_q50_out)
    model_q90.save_model(model_q90_out)

    predictions_out = args.predictions_out or os.path.join(args.out_dir, "correction_model_predictions.csv")
    id_values = (
        valid_df[cols.id_col].values if cols.id_col else np.arange(len(valid_df))
    )
    predictions_df = pd.DataFrame(
        {
            "row_id": id_values,
            "baseline_price": baseline_valid,
            "actual_price": actual_price,
            "actual_ratio": y_valid,
            "pred_ratio_q50": pred_ratio_q50,
            "pred_ratio_q90": pred_ratio_q90,
            "pred_price_q50": pred_price_q50,
            "pred_price_q90": pred_price_q90,
            "abs_error_q50": np.abs(pred_price_q50 - actual_price),
            "error_q50": pred_price_q50 - actual_price,
        }
    )
    write_dataframe_csv_atomic(predictions_df, predictions_out, index=False)

    metrics_out = args.metrics_out or os.path.join(args.out_dir, "correction_model_metrics.json")
    with open(metrics_out, "w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=2)

    print("Saved models:", model_q50_out, model_q90_out)
    print("Validation metrics:", json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
