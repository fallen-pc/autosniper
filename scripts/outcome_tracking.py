from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple

import pandas as pd

from scripts.ai_listing_valuation import load_cached_results
from scripts.ai_price_analysis import load_historical_sales
from shared.data_loader import DATA_DIR


SCORING_DIR = DATA_DIR
SCORING_PATH = SCORING_DIR / "scored_listings.csv"
ENRICHED_PATH = SCORING_DIR / "scored_listings_enriched.csv"
WEEKLY_METRICS_PATH = SCORING_DIR / "model_accuracy_weekly.csv"
TIER_METRICS_PATH = SCORING_DIR / "model_accuracy_by_tier.csv"

PREDICTIONS_SOURCE = SCORING_DIR / "ai_listing_valuations.csv"
VERDICTS_SOURCE = SCORING_DIR / "ai_verdicts.csv"


PREDICTED_COLUMNS = [
    "analysis_timestamp",
    "predicted_resale_price",
    "predicted_profit",
    "predicted_verdict",
    "predicted_score",
    "recommended_max_bid",
]

ACTUAL_COLUMNS = [
    "purchase_price",
    "purchase_date",
    "actual_sale_price",
    "actual_fees_total",
    "reconditioning_cost",
    "actual_profit",
    "outcome_error_abs",
    "outcome_error_pct",
    "is_profitable_pred",
    "is_profitable_actual",
    "hit",
    "settled_date",
]

IDENTITY_COLUMNS = [
    "url",
    "year",
    "make",
    "model",
    "variant",
]


@dataclass
class OutcomeData:
    scored: pd.DataFrame
    weekly_metrics: pd.DataFrame
    tier_metrics: pd.DataFrame
    misses: pd.DataFrame


def _parse_currency(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    cleaned = (
        text.replace("$", "")
        .replace(",", "")
        .replace("AUD", "")
        .replace(" ", "")
    )
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_currency_average(value: object) -> float | None:
    """
    Convert values like "$20,000 - $25,000" into a single float average.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    separators = ["-", "to"]
    for token in separators:
        if token in text:
            parts = [part.strip() for part in text.split(token) if part.strip()]
            numbers = [_parse_currency(part) for part in parts]
            numbers = [num for num in numbers if num is not None]
            if numbers:
                return sum(numbers) / len(numbers)
            break
    return _parse_currency(text)


def _score_to_tier(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 8.0:
        return "Gold"
    if score >= 6.5:
        return "Silver"
    return "Bronze"


def _normalise_verdict(verdict: object) -> str | None:
    if verdict is None:
        return None
    text = str(verdict).strip()
    if not text:
        return None
    normalised = text.lower()
    mapping = {
        "gold": "Gold",
        "silver": "Silver",
        "bronze": "Bronze",
        "great": "Gold",
        "good": "Silver",
        "fair": "Bronze",
        "pass": "Bronze",
        "avoid": "Bronze",
    }
    return mapping.get(normalised, text.title())


def _ensure_directory(path: Path) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


def _ensure_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA
    return df


def _load_predicted_rows() -> pd.DataFrame:
    cached_df = load_cached_results()
    if cached_df.empty:
        return pd.DataFrame(columns=IDENTITY_COLUMNS + PREDICTED_COLUMNS)

    df = cached_df.copy()
    df = _ensure_columns(df, ["url", "analysis_timestamp", "score_out_of_10"])

    df["predicted_resale_price"] = df["carsales_price_estimate"].apply(
        _parse_currency_average
    )
    df["predicted_profit"] = df["expected_profit"].apply(_parse_currency)
    df["predicted_score"] = pd.to_numeric(df["score_out_of_10"], errors="coerce")
    verdict_from_score = df["predicted_score"].apply(_score_to_tier)

    verdict_df = pd.DataFrame()
    if VERDICTS_SOURCE.exists():
        verdict_df = pd.read_csv(VERDICTS_SOURCE)
        verdict_df = _ensure_columns(verdict_df, ["url", "verdict"])
        verdict_df["verdict"] = verdict_df["verdict"].apply(_normalise_verdict)

    df = df.merge(
        verdict_df[["url", "verdict"]] if not verdict_df.empty else pd.DataFrame(),
        on="url",
        how="left",
        suffixes=("", "_verdict"),
    )
    df["predicted_verdict"] = df["verdict"].combine_first(verdict_from_score)
    df["recommended_max_bid"] = df["recommended_max_bid"].apply(_parse_currency)

    df = _ensure_columns(df, IDENTITY_COLUMNS)
    keep_columns = IDENTITY_COLUMNS + [
        "analysis_timestamp",
        "predicted_resale_price",
        "predicted_profit",
        "predicted_verdict",
        "predicted_score",
        "recommended_max_bid",
    ]
    existing_cols = [column for column in keep_columns if column in df.columns]
    predicted = df[existing_cols].drop_duplicates(subset=["url"], keep="last").copy()
    return predicted


def _load_purchase_rows() -> pd.DataFrame:
    sold_df = load_historical_sales()
    if sold_df.empty:
        return pd.DataFrame(columns=IDENTITY_COLUMNS + ["purchase_price", "purchase_date"])

    sold = sold_df.copy()
    sold = _ensure_columns(sold, ["url", "final_price_numeric", "date_sold"])

    relevant_columns = IDENTITY_COLUMNS + ["final_price_numeric", "date_sold"]
    existing_cols = [column for column in relevant_columns if column in sold.columns]
    sold = sold[existing_cols].copy()

    sold.rename(
        columns={
            "final_price_numeric": "purchase_price",
            "date_sold": "purchase_date",
        },
        inplace=True,
    )
    sold.sort_values(by=["purchase_date"], inplace=True, na_position="last")
    sold = sold.drop_duplicates(subset=["url"], keep="last")
    return sold


def load_scored_listings(refresh: bool = False) -> pd.DataFrame:
    if refresh or not SCORING_PATH.exists():
        return update_scored_listings()
    return pd.read_csv(SCORING_PATH)


def _prepare_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    numeric_columns = [
        "predicted_resale_price",
        "predicted_profit",
        "predicted_score",
        "recommended_max_bid",
        "purchase_price",
        "actual_sale_price",
        "actual_fees_total",
        "reconditioning_cost",
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        else:
            df[column] = pd.NA
    return df


def _infer_settled_dates(df: pd.DataFrame) -> pd.Series:
    primary = pd.to_datetime(df.get("settled_date"), errors="coerce")
    if "purchase_date" in df.columns:
        purchase_dates = pd.to_datetime(df["purchase_date"], errors="coerce")
        primary = primary.fillna(purchase_dates)
    fallback = None
    if "time_remaining_or_date_sold" in df.columns:
        fallback = pd.to_datetime(df["time_remaining_or_date_sold"], errors="coerce")
    if fallback is not None:
        primary = primary.fillna(fallback)
    return primary


def update_scored_listings() -> pd.DataFrame:
    predicted = _load_predicted_rows()
    purchases = _load_purchase_rows()
    existing = pd.read_csv(SCORING_PATH) if SCORING_PATH.exists() else pd.DataFrame()

    frames = [frame for frame in (predicted, purchases, existing) if not frame.empty]
    indexes = pd.Index([])
    for frame in frames:
        indexes = indexes.union(frame["url"])

    if indexes.empty:
        combined = pd.DataFrame(columns=IDENTITY_COLUMNS + PREDICTED_COLUMNS + ACTUAL_COLUMNS)
        _ensure_directory(SCORING_PATH)
        combined.to_csv(SCORING_PATH, index=False)
        return combined

    combined = pd.DataFrame(index=indexes)
    predicted_idx = predicted.set_index("url") if not predicted.empty else pd.DataFrame()
    purchases_idx = purchases.set_index("url") if not purchases.empty else pd.DataFrame()
    existing_idx = existing.set_index("url") if not existing.empty else pd.DataFrame()

    def assign(column: str, sources: Iterable[pd.DataFrame]) -> None:
        combined[column] = pd.NA
        for source in sources:
            if source.empty or column not in source.columns:
                continue
            combined.loc[source.index, column] = source[column]

    for column in IDENTITY_COLUMNS:
        assign(column, (existing_idx, predicted_idx, purchases_idx))

    for column in PREDICTED_COLUMNS:
        assign(column, (existing_idx, predicted_idx))

    assign("purchase_price", (existing_idx, purchases_idx))
    assign("purchase_date", (existing_idx, purchases_idx))

    for column in ACTUAL_COLUMNS:
        if column in ("purchase_price", "purchase_date"):
            continue
        assign(column, (existing_idx,))

    combined = combined.reset_index().rename(columns={"index": "url"})
    combined = combined.loc[:, ~combined.columns.duplicated()]
    combined = _ensure_columns(combined, IDENTITY_COLUMNS + PREDICTED_COLUMNS + ACTUAL_COLUMNS)
    combined = combined.sort_values(by=["analysis_timestamp", "purchase_date"], ascending=False)

    _ensure_directory(SCORING_PATH)
    combined.to_csv(SCORING_PATH, index=False)
    return combined


def compute_outcome_metrics() -> OutcomeData:
    df = update_scored_listings()
    df = _prepare_numeric_columns(df)

    if "reconditioning_cost" not in df.columns:
        df["reconditioning_cost"] = 0.0

    df["actual_sale_price"] = df["actual_sale_price"].combine_first(pd.Series(dtype=float))
    df["actual_fees_total"] = df["actual_fees_total"].fillna(0.0)
    df["reconditioning_cost"] = df["reconditioning_cost"].fillna(0.0)

    df["actual_profit"] = pd.NA
    has_actuals = df["actual_sale_price"].notna()
    df.loc[has_actuals, "actual_profit"] = (
        df.loc[has_actuals, "actual_sale_price"]
        - (
            df.loc[has_actuals, "purchase_price"].fillna(0.0)
            + df.loc[has_actuals, "actual_fees_total"].fillna(0.0)
            + df.loc[has_actuals, "reconditioning_cost"].fillna(0.0)
        )
    )

    df["outcome_error_abs"] = pd.NA
    df.loc[has_actuals, "outcome_error_abs"] = (
        df.loc[has_actuals, "actual_sale_price"]
        - df.loc[has_actuals, "predicted_resale_price"]
    ).abs()

    df["outcome_error_pct"] = pd.NA
    denominator = df.loc[has_actuals, "actual_sale_price"]
    valid_denominator = denominator.replace({0: pd.NA})
    df.loc[has_actuals, "outcome_error_pct"] = (
        df.loc[has_actuals, "outcome_error_abs"] / valid_denominator
    )

    df["is_profitable_pred"] = df["predicted_profit"].apply(
        lambda value: value > 0 if pd.notna(value) else pd.NA
    )
    df["is_profitable_actual"] = df["actual_profit"].apply(
        lambda value: value > 0 if pd.notna(value) else pd.NA
    )

    df["hit"] = pd.NA
    both_flags = df["is_profitable_pred"].notna() & df["is_profitable_actual"].notna()
    df.loc[both_flags, "hit"] = (
        df.loc[both_flags, "is_profitable_pred"] == df.loc[both_flags, "is_profitable_actual"]
    )

    df["settled_date"] = _infer_settled_dates(df)

    _ensure_directory(SCORING_PATH)
    df.to_csv(SCORING_PATH, index=False)
    df.to_csv(ENRICHED_PATH, index=False)

    metrics_df = df[df["hit"].notna()].copy()
    metrics_df["settled_date"] = pd.to_datetime(metrics_df["settled_date"], errors="coerce")
    metrics_df = metrics_df.dropna(subset=["settled_date"])
    metrics_df["week"] = metrics_df["settled_date"].dt.to_period("W").dt.start_time

    if not metrics_df.empty:
        weekly_metrics = (
            metrics_df.groupby("week")
            .agg(
                accuracy=("hit", "mean"),
                mae_price=("outcome_error_abs", "mean"),
                mape_price=("outcome_error_pct", "mean"),
                profit_calibration=("actual_profit", "mean"),
            )
            .reset_index()
            .sort_values(by="week")
        )
    else:
        weekly_metrics = pd.DataFrame(columns=["week", "accuracy", "mae_price", "mape_price", "profit_calibration"])

    if not metrics_df.empty:
        tier_metrics = (
            metrics_df.groupby("predicted_verdict")
            .agg(
                accuracy=("hit", "mean"),
                mae_price=("outcome_error_abs", "mean"),
                count=("predicted_verdict", "size"),
            )
            .reset_index()
            .sort_values(by="accuracy", ascending=False)
        )
    else:
        tier_metrics = pd.DataFrame(columns=["predicted_verdict", "accuracy", "mae_price", "count"])

    misses_source = df[df["outcome_error_pct"].notna()].copy()
    misses = (
        misses_source.sort_values(by="outcome_error_pct", ascending=False)
        .head(10)
        .loc[
            :,
            [
                "url",
                "year",
                "make",
                "model",
                "variant",
                "predicted_resale_price",
                "actual_sale_price",
                "outcome_error_abs",
                "outcome_error_pct",
            ],
        ]
    )

    weekly_metrics.to_csv(WEEKLY_METRICS_PATH, index=False)
    tier_metrics.to_csv(TIER_METRICS_PATH, index=False)

    return OutcomeData(
        scored=df,
        weekly_metrics=weekly_metrics,
        tier_metrics=tier_metrics,
        misses=misses,
    )


__all__ = [
    "OutcomeData",
    "compute_outcome_metrics",
    "load_scored_listings",
    "update_scored_listings",
]
