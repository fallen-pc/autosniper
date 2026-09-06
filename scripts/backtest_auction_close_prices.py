"""Shadow backtest for auction close-price predictions.

This is deliberately separate from the live valuation and bidding paths.  It
uses only a verified final sale price as the target, and reconstructs each
prediction from the latest retained snapshot at least N hours before the
auction's recorded sale day.  Comparable prices are limited to sales on an
earlier calendar day, preventing an outcome from becoming its own comparable.

Example:
    python -m scripts.backtest_auction_close_prices \
        --out-dir artifacts/shadow_auction_backtest
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.comps_engine import parse_currency, parse_numeric
from shared.data_loader import dataset_path
from shared.repair_features import build_repair_features

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = dataset_path("vehicle_state.csv")
DEFAULT_SOLD_PATH = dataset_path("sold_cars.csv")
DEFAULT_SNAPSHOTS_PATH = dataset_path("active_snapshots.csv")
DEFAULT_SNAPSHOT_ARCHIVE = ROOT_DIR / "CSV_data" / "archives" / "active_snapshots"

TARGET_COLUMNS = [
    "url",
    "final_sale_price",
    "sale_price_source",
    "date_sold",
    "year",
    "make",
    "model",
    "variant",
    "body_type",
    "transmission",
    "fuel_type",
    "odometer_reading",
    "location",
    "general_condition",
    "canonical_tag",
]

PRE_AUCTION_FEATURES = [
    "comps_p50",
    "comps_count",
    "year_numeric",
    "odometer_numeric",
    "vehicle_age_years",
    "repair_severity",
    "repair_tag_count",
    "prediction_month",
    "canonical_tag",
    "make",
    "model",
    "variant",
    "body_type",
    "transmission",
    "fuel_type",
    "location",
]
LIVE_FEATURES = [
    *PRE_AUCTION_FEATURES,
    "current_bid",
    "bid_count",
    "time_remaining_hours",
    "auction_site",
]
CATEGORICAL_FEATURES = {
    "canonical_tag",
    "make",
    "model",
    "variant",
    "body_type",
    "transmission",
    "fuel_type",
    "location",
    "auction_site",
}
FORBIDDEN_FEATURES = {
    "final_sale_price",
    "target_price",
    "date_sold",
    "sale_date",
    "sale_price_source",
    "url",
    "snapshot_ts",
    "prediction_ts",
    "latest_comp_sale_date",
}


@dataclass(frozen=True)
class MetricSummary:
    count: int
    mae: float
    rmse: float
    wape: float
    bias: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "count": self.count,
            "mae": self.mae,
            "rmse": self.rmse,
            "wape": self.wape,
            "bias": self.bias,
        }


def _normalise_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "UNKNOWN"
    text = str(value).strip()
    return text if text else "UNKNOWN"


def _canonical_comp_key(row: pd.Series) -> str:
    """Return a stable comparable lane, falling back for unclassified rows."""
    tag = _normalise_text(row.get("canonical_tag"))
    if tag.upper() not in {"UNKNOWN", "UNCLASSIFIED", "NAN", "NONE"}:
        return f"tag:{tag.lower()}"
    return "fallback:" + "|".join(
        _normalise_text(row.get(column)).lower()
        for column in ("make", "model", "body_type", "transmission", "fuel_type")
    )


def _parse_price(value: object) -> float:
    parsed = parse_currency(value)
    return float(parsed) if parsed is not None and not pd.isna(parsed) else float("nan")


def _parse_horizons(raw: str) -> list[float]:
    values = sorted({float(part.strip()) for part in raw.split(",") if part.strip()}, reverse=True)
    if not values or any(value <= 0 for value in values):
        raise ValueError("--horizons must contain one or more positive hour values.")
    return values


def _parse_rolling_cutoffs(raw: str) -> list[pd.Timestamp]:
    """Parse ordered UTC validation-window starts for rolling evaluation."""
    if not raw.strip():
        return []
    cutoffs = [pd.Timestamp(value.strip(), tz="UTC") for value in raw.split(",") if value.strip()]
    if any(cutoff.time() != pd.Timestamp(0, tz="UTC").time() for cutoff in cutoffs):
        raise ValueError("--rolling-cutoffs values must be calendar dates (for example, 2026-06-01).")
    if cutoffs != sorted(set(cutoffs)):
        raise ValueError("--rolling-cutoffs must be unique and in ascending order.")
    return cutoffs


def _load_snapshots(snapshot_path: Path, archive_dir: Path) -> pd.DataFrame:
    paths = [snapshot_path]
    if archive_dir.exists():
        paths.extend(sorted(archive_dir.glob("active_snapshots_*.csv")))
    frames = [pd.read_csv(path, low_memory=False) for path in paths if path.exists()]
    if not frames:
        return pd.DataFrame()
    snapshots = pd.concat(frames, ignore_index=True, sort=False)
    snapshots["url"] = snapshots["url"].astype(str).str.strip()
    snapshots["snapshot_ts"] = pd.to_datetime(snapshots["snapshot_ts"], errors="coerce", utc=True)
    for column in ("price_numeric", "bids_numeric", "time_remaining_hours"):
        snapshots[column] = pd.to_numeric(snapshots.get(column), errors="coerce")
    return snapshots.drop_duplicates(
        subset=["url", "snapshot_ts", "price_numeric", "bids_numeric", "time_remaining_hours"],
        keep="first",
    )


def load_verified_sales(state_path: Path, sold_path: Path) -> pd.DataFrame:
    """Load targets whose final auction price was explicitly verified by the scraper."""
    state = pd.read_csv(state_path, low_memory=False)
    sold = pd.read_csv(sold_path, low_memory=False)
    state["url"] = state["url"].astype(str).str.strip()
    sold["url"] = sold["url"].astype(str).str.strip()
    state["target_price"] = state["final_sale_price"].apply(_parse_price)
    state_status = state.get("state", pd.Series("", index=state.index)).astype(str).str.lower().str.strip()
    source = state.get("sale_price_source", pd.Series("", index=state.index)).fillna("").astype(str).str.strip()
    verified = state.loc[(state_status == "sold") & state["target_price"].gt(0) & source.ne("")].copy()
    sold_columns = [column for column in TARGET_COLUMNS if column in sold.columns and column != "final_sale_price"]
    joined = verified[["url", "target_price", "sale_price_source"]].merge(
        sold[sold_columns], on="url", how="inner", validate="one_to_one"
    )
    joined["sale_date"] = pd.to_datetime(joined["date_sold"], errors="coerce", utc=True).dt.normalize()
    joined = joined.dropna(subset=["sale_date"]).copy()

    # The sold listing archive is our static-detail companion.  Reject any row
    # where its archived price disagrees with the verified state target.
    sold_prices = sold[["url", "price"]].copy()
    sold_prices["sold_archive_price"] = sold_prices["price"].apply(_parse_price)
    joined = joined.merge(sold_prices[["url", "sold_archive_price"]], on="url", how="left")
    joined = joined.loc[joined["sold_archive_price"].eq(joined["target_price"])].copy()
    joined["comp_key"] = joined.apply(_canonical_comp_key, axis=1)
    return joined.reset_index(drop=True)


def load_historical_comps(sold_path: Path) -> pd.DataFrame:
    """Load prior sale evidence used only as chronological comparables."""
    sold = pd.read_csv(sold_path, low_memory=False)
    sold["url"] = sold["url"].astype(str).str.strip()
    sold["comp_price"] = sold["price"].apply(_parse_price)
    sold["comp_sale_date"] = pd.to_datetime(sold["date_sold"], errors="coerce", utc=True).dt.normalize()
    sold = sold.loc[sold["comp_price"].gt(0) & sold["comp_sale_date"].notna()].copy()
    sold["comp_key"] = sold.apply(_canonical_comp_key, axis=1)
    return sold[["url", "comp_key", "comp_price", "comp_sale_date"]].sort_values(
        ["comp_key", "comp_sale_date", "url"]
    )


def select_as_of_snapshots(
    sales: pd.DataFrame, snapshots: pd.DataFrame, horizon_hours: float
) -> pd.DataFrame:
    """Take the latest snapshot at least ``horizon_hours`` before the sale day ends."""
    if snapshots.empty:
        return pd.DataFrame()
    sale_end = sales[["url", "sale_date"]].copy()
    sale_end["sale_end_ts"] = sale_end["sale_date"] + pd.Timedelta(days=1)
    candidates = snapshots.merge(sale_end[["url", "sale_end_ts"]], on="url", how="inner")
    eligible = candidates.loc[
        candidates["snapshot_ts"].notna()
        & candidates["snapshot_ts"].lt(candidates["sale_end_ts"])
        & candidates["time_remaining_hours"].ge(horizon_hours)
    ].copy()
    if eligible.empty:
        return eligible
    eligible = eligible.sort_values(["url", "snapshot_ts"])
    chosen = eligible.drop_duplicates(subset=["url"], keep="last").copy()
    chosen = chosen.rename(columns={"snapshot_ts": "prediction_ts", "price_numeric": "current_bid", "bids_numeric": "bid_count"})
    return chosen[
        [
            "url",
            "prediction_ts",
            "current_bid",
            "bid_count",
            "time_remaining_hours",
            "auction_site",
        ]
    ]


def add_as_of_comps(rows: pd.DataFrame, historical_comps: pd.DataFrame) -> pd.DataFrame:
    """Add a median of strictly earlier calendar-day comparable sales per row."""
    by_key: dict[str, tuple[pd.DatetimeIndex, np.ndarray]] = {}
    for key, group in historical_comps.groupby("comp_key", sort=False):
        ordered = group.sort_values("comp_sale_date")
        dates = pd.DatetimeIndex(ordered["comp_sale_date"])
        prices = ordered["comp_price"].to_numpy(dtype=float)
        by_key[str(key)] = (dates, prices)

    medians: list[float] = []
    counts: list[int] = []
    latest_dates: list[pd.Timestamp | pd.NaT] = []
    for row in rows.itertuples(index=False):
        dates, prices = by_key.get(str(row.comp_key), (pd.DatetimeIndex([], tz=timezone.utc), np.array([], dtype=float)))
        # Strictly earlier calendar day: prices from the sale day itself are not
        # yet known at any intraday prediction time.
        cutoff = pd.Timestamp(row.prediction_ts).normalize()
        end_index = int(dates.searchsorted(cutoff, side="left"))
        prior_prices = prices[:end_index]
        medians.append(float(np.median(prior_prices)) if len(prior_prices) else float("nan"))
        counts.append(int(len(prior_prices)))
        latest_dates.append(
            dates[end_index - 1] if end_index else pd.NaT
        )

    result = rows.copy()
    result["comps_p50"] = medians
    result["comps_count"] = counts
    result["latest_comp_sale_date"] = latest_dates
    return result


def add_model_features(rows: pd.DataFrame) -> pd.DataFrame:
    result = rows.copy()
    result["year_numeric"] = pd.to_numeric(result.get("year"), errors="coerce")
    result["odometer_numeric"] = result.get("odometer_reading", pd.Series(index=result.index, dtype=object)).apply(parse_numeric)
    result["odometer_numeric"] = pd.to_numeric(result["odometer_numeric"], errors="coerce")
    result["vehicle_age_years"] = result["prediction_ts"].dt.year - result["year_numeric"]
    result.loc[result["vehicle_age_years"].lt(0), "vehicle_age_years"] = np.nan
    result["prediction_month"] = result["prediction_ts"].dt.month

    repair = result.get("general_condition", pd.Series("", index=result.index)).apply(build_repair_features)
    result["repair_severity"] = repair.apply(lambda features: float(features.severity))
    result["repair_tag_count"] = repair.apply(lambda features: int(len(features.tags)))
    for column in ("canonical_tag", "make", "model", "variant", "body_type", "transmission", "fuel_type", "location", "auction_site"):
        result[column] = result.get(column, pd.Series("UNKNOWN", index=result.index)).apply(_normalise_text)
    return result


def build_backtest_rows(
    sales: pd.DataFrame,
    snapshots: pd.DataFrame,
    historical_comps: pd.DataFrame,
    horizon_hours: float,
    min_comps: int,
) -> pd.DataFrame:
    chosen = select_as_of_snapshots(sales, snapshots, horizon_hours)
    if chosen.empty:
        return chosen
    rows = sales.merge(chosen, on="url", how="inner", validate="one_to_one")
    rows = add_as_of_comps(rows, historical_comps)
    rows = rows.loc[rows["comps_count"].ge(min_comps)].copy()
    rows = add_model_features(rows)
    rows["horizon_hours"] = float(horizon_hours)
    validate_as_of_rows(rows, horizon_hours)
    return rows.reset_index(drop=True)


def validate_as_of_rows(rows: pd.DataFrame, horizon_hours: float) -> None:
    """Fail closed if a feature could have been observed after the outcome."""
    if rows.empty:
        return
    if not rows["prediction_ts"].lt(rows["sale_date"] + pd.Timedelta(days=1)).all():
        raise ValueError("Leakage guard failed: a prediction snapshot is not before the recorded sale day ends.")
    if not rows["time_remaining_hours"].ge(horizon_hours).all():
        raise ValueError("Leakage guard failed: a row is closer to close than its requested horizon.")
    latest = rows["latest_comp_sale_date"].dropna()
    if not latest.empty and not latest.lt(rows.loc[latest.index, "prediction_ts"].dt.normalize()).all():
        raise ValueError("Leakage guard failed: a comparable is not from an earlier calendar day.")
    forbidden = FORBIDDEN_FEATURES.intersection(PRE_AUCTION_FEATURES + LIVE_FEATURES)
    if forbidden:
        raise ValueError(f"Leakage guard failed: forbidden model feature(s): {sorted(forbidden)}")


def _metric_summary(actual: pd.Series, predicted: pd.Series) -> MetricSummary:
    actual_values = actual.to_numpy(dtype=float)
    predicted_values = predicted.to_numpy(dtype=float)
    error = predicted_values - actual_values
    denominator = float(np.abs(actual_values).sum()) or 1.0
    return MetricSummary(
        count=len(actual_values),
        mae=float(np.abs(error).mean()),
        rmse=float(np.sqrt(np.square(error).mean())),
        wape=float(np.abs(error).sum() / denominator),
        bias=float(error.mean()),
    )


def _feature_frame(rows: pd.DataFrame, feature_names: Iterable[str]) -> pd.DataFrame:
    frame = rows[list(feature_names)].copy()
    for column in frame.columns:
        if column in CATEGORICAL_FEATURES:
            frame[column] = frame[column].fillna("UNKNOWN").astype(str)
    return frame


def apply_live_bid_floor(predictions: np.ndarray, current_bids: pd.Series) -> np.ndarray:
    """A sold vehicle cannot finish below a bid observed before its close."""
    bids = pd.to_numeric(current_bids, errors="coerce").to_numpy(dtype=float)
    return np.where(np.isfinite(bids) & (bids > 0), np.maximum(predictions, bids), predictions)


def train_and_predict(
    rows: pd.DataFrame,
    feature_names: list[str],
    holdout_days: int,
    iterations: int,
    validation_start: pd.Timestamp | None = None,
    validation_end: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fit only on earlier prediction timestamps and score the later holdout."""
    ordered = rows.sort_values("prediction_ts").copy()
    cutoff = (
        validation_start
        if validation_start is not None
        else ordered["prediction_ts"].max() - pd.Timedelta(days=holdout_days)
    )
    if validation_end is not None and validation_end <= cutoff:
        raise ValueError("Rolling validation end must be after its start.")
    train = ordered.loc[ordered["prediction_ts"].lt(cutoff)].copy()
    valid_mask = ordered["prediction_ts"].ge(cutoff)
    if validation_end is not None:
        valid_mask &= ordered["prediction_ts"].lt(validation_end)
    valid = ordered.loc[valid_mask].copy()
    if len(train) < 30 or len(valid) < 10:
        raise ValueError(
            f"Insufficient chronological rows for model training: train={len(train)}, valid={len(valid)}."
        )

    x_train = _feature_frame(train, feature_names)
    x_valid = _feature_frame(valid, feature_names)
    cat_indices = [index for index, column in enumerate(x_train.columns) if column in CATEGORICAL_FEATURES]
    model = CatBoostRegressor(
        loss_function="MAE",
        eval_metric="MAE",
        iterations=iterations,
        depth=7,
        learning_rate=0.05,
        random_seed=42,
        od_type="Iter",
        od_wait=60,
        verbose=False,
        allow_writing_files=False,
    )
    model.fit(
        Pool(x_train, train["target_price"], cat_features=cat_indices),
        eval_set=Pool(x_valid, valid["target_price"], cat_features=cat_indices),
        use_best_model=True,
    )
    prediction = model.predict(x_valid)
    if "current_bid" in feature_names:
        prediction = apply_live_bid_floor(prediction, valid["current_bid"])
    valid["model_prediction"] = prediction
    return valid, {
        "cutoff": cutoff.isoformat(),
        "validation_end": validation_end.isoformat() if validation_end is not None else None,
        "rows_train": len(train),
        "rows_valid": len(valid),
        "features": list(feature_names),
        "best_iteration": int(model.get_best_iteration()),
    }


def _prediction_rows(
    valid: pd.DataFrame,
    model_type: str,
    evaluation: str,
) -> pd.DataFrame:
    columns = ["url", "horizon_hours", "prediction_ts", "sale_date", "target_price", "comps_p50", "comps_count"]
    result = valid[columns].copy()
    result["model_type"] = model_type
    result["evaluation"] = evaluation
    if model_type == "comps_baseline":
        result["prediction"] = result["comps_p50"]
    else:
        result["prediction"] = valid["model_prediction"].to_numpy()
    return result


def _evaluate_window(
    rows: pd.DataFrame,
    horizon: float,
    args: argparse.Namespace,
    evaluation: str,
    validation_start: pd.Timestamp | None = None,
    validation_end: pd.Timestamp | None = None,
) -> tuple[dict[str, Any], list[pd.DataFrame]]:
    pre_valid, pre_info = train_and_predict(
        rows, PRE_AUCTION_FEATURES, args.holdout_days, args.iterations, validation_start, validation_end
    )
    live_valid, live_info = train_and_predict(
        rows, LIVE_FEATURES, args.holdout_days, args.iterations, validation_start, validation_end
    )
    baseline = _metric_summary(pre_valid["target_price"], pre_valid["comps_p50"])
    pre_summary = _metric_summary(pre_valid["target_price"], pre_valid["model_prediction"])
    live_summary = _metric_summary(live_valid["target_price"], live_valid["model_prediction"])
    result = {
        "eligible_rows": len(rows),
        "baseline": baseline.to_dict(),
        "pre_auction": {**pre_info, "metrics": pre_summary.to_dict()},
        "live": {**live_info, "metrics": live_summary.to_dict()},
    }
    return result, [
        _prediction_rows(pre_valid, "comps_baseline", evaluation),
        _prediction_rows(pre_valid, "pre_auction_catboost", evaluation),
        _prediction_rows(live_valid, "live_catboost", evaluation),
    ]


def _write_report(path: Path, metrics: dict[str, Any]) -> None:
    lines = ["# Auction close-price shadow backtest", "", "This report is a shadow evaluation only; it does not change live bidding or valuation.", ""]
    for horizon, result in metrics["horizons"].items():
        lines.extend(
            [
                f"## {horizon}-hour horizon",
                "",
                f"- Eligible rows: {result['eligible_rows']:,}",
                f"- Holdout rows: {result['pre_auction']['rows_valid']:,}",
                f"- Comparable-only MAE: ${result['baseline']['mae']:,.0f}",
                f"- Pre-auction model MAE: ${result['pre_auction']['metrics']['mae']:,.0f}",
                f"- Live model MAE: ${result['live']['metrics']['mae']:,.0f}",
                "",
            ]
        )
    rolling = metrics.get("rolling_windows", {})
    if rolling:
        lines.extend(["## Rolling validation windows", ""])
        for window, horizon_results in rolling.items():
            lines.extend([f"### {window}", ""])
            for horizon, result in horizon_results.items():
                if "reason" in result:
                    lines.append(f"- {horizon}h: not evaluated ({result['reason']})")
                    continue
                lines.append(
                    f"- {horizon}h: baseline ${result['baseline']['mae']:,.0f}; "
                    f"pre-auction ${result['pre_auction']['metrics']['mae']:,.0f}; "
                    f"live ${result['live']['metrics']['mae']:,.0f} "
                    f"({result['live']['metrics']['count']:,} validation rows)"
                )
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_backtest(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    sales = load_verified_sales(args.state_path, args.sold_path)
    snapshots = _load_snapshots(args.snapshots_path, args.snapshot_archive_dir)
    historical_comps = load_historical_comps(args.sold_path)
    metrics: dict[str, Any] = {
        "run_type": "shadow_backtest",
        "verified_sales_loaded": len(sales),
        "snapshot_rows_loaded": len(snapshots),
        "holdout_days": args.holdout_days,
        "min_comps": args.min_comps,
        "horizons": {},
        "rolling_windows": {},
    }
    predictions: list[pd.DataFrame] = []

    for horizon in _parse_horizons(args.horizons):
        rows = build_backtest_rows(sales, snapshots, historical_comps, horizon, args.min_comps)
        if rows.empty:
            metrics["horizons"][str(horizon)] = {"eligible_rows": 0, "reason": "no eligible rows"}
            continue
        latest_result, latest_predictions = _evaluate_window(rows, horizon, args, "latest_holdout")
        metrics["horizons"][str(horizon)] = latest_result
        predictions.extend(latest_predictions)
        for cutoff in _parse_rolling_cutoffs(args.rolling_cutoffs):
            end = cutoff + pd.Timedelta(days=args.rolling_holdout_days)
            label = f"{cutoff.date().isoformat()}_to_{end.date().isoformat()}"
            try:
                result, fold_predictions = _evaluate_window(rows, horizon, args, label, cutoff, end)
            except ValueError as exc:
                metrics["rolling_windows"].setdefault(label, {})[str(horizon)] = {"reason": str(exc)}
                continue
            metrics["rolling_windows"].setdefault(label, {})[str(horizon)] = result
            predictions.extend(fold_predictions)

    if predictions:
        output = pd.concat(predictions, ignore_index=True, sort=False)
        output["absolute_error"] = (output["prediction"] - output["target_price"]).abs()
        write_dataframe_csv_atomic(output, out_dir / "predictions.csv", index=False)
    with (out_dir / "metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=2)
    _write_report(out_dir / "report.md", metrics)
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--sold-path", type=Path, default=DEFAULT_SOLD_PATH)
    parser.add_argument("--snapshots-path", type=Path, default=DEFAULT_SNAPSHOTS_PATH)
    parser.add_argument("--snapshot-archive-dir", type=Path, default=DEFAULT_SNAPSHOT_ARCHIVE)
    parser.add_argument("--out-dir", type=Path, default=ROOT_DIR / "artifacts" / "shadow_auction_backtest")
    parser.add_argument("--horizons", default="24,6", help="Comma-separated pre-close horizons in hours.")
    parser.add_argument("--holdout-days", type=int, default=45)
    parser.add_argument(
        "--rolling-cutoffs",
        default="",
        help="Comma-separated validation-start dates for leakage-safe rolling windows.",
    )
    parser.add_argument("--rolling-holdout-days", type=int, default=31)
    parser.add_argument("--min-comps", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics = run_backtest(args)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
