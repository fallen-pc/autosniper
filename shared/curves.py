"""Curve storage and interpolation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from shared.audit import append_audit_snapshot
from shared.data_loader import dataset_path
from shared.pipe_keys import looks_like_pipe_key, parse_pipe_key
from shared.validators import (
    compute_price_per_km_bucket,
    validate_curves_df,
    validate_curves_v2_df,
)

CURVE_MODEL = os.getenv("CURVE_MODEL", "v2").strip().lower()

CURVE_COLUMNS_V1: Sequence[str] = (
    "group_id",
    "series",
    "anchor_year",
    "km_anchor",
    "price_low",
    "price_high",
    "price_median",
    "price_per_km_bucket",
    "source",
    "created_at",
)

CURVE_COLUMNS_V2: Sequence[str] = (
    "canonical_tag",
    "anchor_year",
    "km_bucket",
    "price_low",
    "price_mid",
    "price_high",
)

CURVE_COLUMNS = CURVE_COLUMNS_V2 if CURVE_MODEL == "v2" else CURVE_COLUMNS_V1


def curve_model() -> str:
    return CURVE_MODEL


def curve_dataset_name() -> str:
    return "curves_v2.csv" if CURVE_MODEL == "v2" else "curves.csv"


def _to_numeric(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: object) -> int | None:
    number = _to_numeric(value)
    if number is None:
        return None
    try:
        return int(round(number))
    except (TypeError, ValueError):
        return None


def _fill_median_row(row: pd.Series) -> pd.Series:
    if pd.notna(row.get("price_median")):
        return row
    low = _to_numeric(row.get("price_low"))
    high = _to_numeric(row.get("price_high"))
    if low is not None and high is not None:
        row["price_median"] = round((low + high) / 2.0)
    return row


def _ensure_v1_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in CURVE_COLUMNS_V1:
        if column not in df.columns:
            df[column] = None
    return df[list(CURVE_COLUMNS_V1)].copy()


def _ensure_v2_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in CURVE_COLUMNS_V2:
        if column not in df.columns:
            df[column] = None
    return df[list(CURVE_COLUMNS_V2)].copy()


def _normalize_v2_for_compat(df: pd.DataFrame) -> pd.DataFrame:
    """Add v1-compatible columns so existing readers keep working."""
    working = df.copy()
    working["canonical_tag"] = working.get("canonical_tag", "").astype(str).str.strip()
    working["anchor_year"] = working["anchor_year"].apply(_to_int)
    working["km_bucket"] = working["km_bucket"].apply(_to_int)
    working["price_low"] = working["price_low"].apply(_to_int)
    working["price_high"] = working["price_high"].apply(_to_int)
    working["price_mid"] = working["price_mid"].apply(_to_int)

    fill_mask = working["price_mid"].isna()
    if fill_mask.any():
        low = working["price_low"]
        high = working["price_high"]
        working.loc[fill_mask, "price_mid"] = ((low + high) / 2.0).round()

    working["group_id"] = working["canonical_tag"]
    working["series"] = ""
    working["km_anchor"] = working["km_bucket"]
    working["price_median"] = working["price_mid"]
    working["price_per_km_bucket"] = working.apply(
        lambda row: compute_price_per_km_bucket(row.get("price_median"), row.get("km_anchor")),
        axis=1,
    )
    return working


def load_curves(path: Path | None = None) -> pd.DataFrame:
    curve_path = path or dataset_path(curve_dataset_name())
    if not curve_path.exists():
        columns = CURVE_COLUMNS_V2 if CURVE_MODEL == "v2" else CURVE_COLUMNS_V1
        return pd.DataFrame(columns=list(columns))
    df = pd.read_csv(curve_path)

    if CURVE_MODEL == "v2":
        df = _ensure_v2_columns(df)
        df = _normalize_v2_for_compat(df)
        return df

    df = _ensure_v1_columns(df)
    df["anchor_year"] = df["anchor_year"].apply(_to_int)
    df["km_anchor"] = df["km_anchor"].apply(_to_int)
    df["price_low"] = df["price_low"].apply(_to_int)
    df["price_high"] = df["price_high"].apply(_to_int)
    df["price_median"] = df["price_median"].apply(_to_int)
    df = df.apply(_fill_median_row, axis=1)
    df["price_per_km_bucket"] = df.apply(
        lambda row: compute_price_per_km_bucket(row.get("price_median"), row.get("km_anchor")),
        axis=1,
    )
    return df


def save_curves(df: pd.DataFrame, path: Path | None = None) -> None:
    curve_path = path or dataset_path(curve_dataset_name())
    curve_path.parent.mkdir(parents=True, exist_ok=True)

    if CURVE_MODEL == "v2":
        working, _ = validate_curves_v2_df(df)
        working = _ensure_v2_columns(working)
        working.to_csv(curve_path, index=False)
        append_audit_snapshot(working, curve_path)
        return

    working, _ = validate_curves_df(df)
    working = _ensure_v1_columns(working)
    if "created_at" in working.columns:
        working["created_at"] = working["created_at"].fillna(
            datetime.utcnow().isoformat(timespec="seconds")
        )
    working.to_csv(curve_path, index=False)
    append_audit_snapshot(working, curve_path)


def get_curve_points(
    curves_df: pd.DataFrame, group_id: str, anchor_year: int
) -> List[Tuple[int, int]]:
    if curves_df.empty:
        return []
    subset = curves_df[
        (curves_df["group_id"] == group_id) & (curves_df["anchor_year"] == anchor_year)
    ].copy()
    subset = subset.dropna(subset=["km_anchor", "price_median"])
    if subset.empty:
        return []
    subset["km_anchor"] = subset["km_anchor"].apply(_to_int)
    subset["price_median"] = subset["price_median"].apply(_to_int)
    subset = subset.dropna(subset=["km_anchor", "price_median"])
    points = list(
        subset.sort_values("km_anchor")[["km_anchor", "price_median"]].itertuples(index=False, name=None)
    )
    return [(int(km), int(price)) for km, price in points]


def interpolate_price_by_km(points: Iterable[Tuple[int, int]], km: float | int | None) -> Optional[float]:
    if km is None:
        return None
    points_list = sorted(points, key=lambda p: p[0])
    if not points_list:
        return None
    km_value = float(km)
    if km_value <= points_list[0][0]:
        return float(points_list[0][1])
    if km_value >= points_list[-1][0]:
        return float(points_list[-1][1])
    for (km_a, price_a), (km_b, price_b) in zip(points_list, points_list[1:]):
        if km_a <= km_value <= km_b:
            if km_b == km_a:
                return float(price_a)
            ratio = (km_value - km_a) / float(km_b - km_a)
            return float(price_a) + ratio * float(price_b - price_a)
    return None


def interpolate_base_by_year(
    curves_df: pd.DataFrame,
    group_id: str,
    year: int | None,
    km: float | int | None,
) -> Optional[float]:
    if curves_df.empty or not group_id or year is None or km is None:
        return None
    subset = curves_df[curves_df["group_id"] == group_id].copy()
    if looks_like_pipe_key(group_id):
        parsed = parse_pipe_key(group_id)
        if parsed:
            target_model, target_group_key, target_series, _ = parsed
            def _same_base_group(value: object) -> bool:
                if not isinstance(value, str):
                    return False
                parts = parse_pipe_key(value)
                if not parts:
                    return False
                model, group_key, series, _ = parts
                return (
                    model == target_model
                    and group_key == target_group_key
                    and series == target_series
                )
            subset = curves_df[curves_df["group_id"].apply(_same_base_group)].copy()
    subset = subset.dropna(subset=["anchor_year"])
    if subset.empty:
        return None
    anchor_years = sorted({int(y) for y in subset["anchor_year"].dropna()})
    if not anchor_years:
        return None

    def _price_for_anchor(anchor_year: int) -> Optional[float]:
        anchor_group_id = group_id
        if looks_like_pipe_key(group_id):
            matched = subset[subset["anchor_year"] == anchor_year]
            if not matched.empty and "group_id" in matched.columns:
                anchor_group_id = str(matched.iloc[0]["group_id"])
        points = get_curve_points(subset, anchor_group_id, anchor_year)
        return interpolate_price_by_km(points, km)

    # Do not extrapolate outside anchor year band.
    if year < anchor_years[0] or year > anchor_years[-1]:
        return None

    lower_year = anchor_years[0]
    upper_year = anchor_years[-1]
    for start, end in zip(anchor_years, anchor_years[1:]):
        if start <= year <= end:
            lower_year = start
            upper_year = end
            break

    lower_price = _price_for_anchor(lower_year)
    upper_price = _price_for_anchor(upper_year)
    if lower_price is None and upper_price is None:
        return None
    if lower_price is None:
        return upper_price
    if upper_price is None:
        return lower_price

    if upper_year == lower_year:
        return lower_price
    ratio = (year - lower_year) / float(upper_year - lower_year)
    return lower_price + ratio * (upper_price - lower_price)
