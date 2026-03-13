"""Curve storage and interpolation helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from shared.audit import append_audit_snapshot
from shared.curve_versioning import snapshot_curve_version
from shared.data_loader import dataset_path


CURVE_COLUMNS: Sequence[str] = (
    "canonical_tag",
    "anchor_year",
    "km_bucket",
    "price_low",
    "price_mid",
    "price_high",
)

LEGACY_COLUMNS = {"group_id", "series", "km_anchor", "price_median"}


def detect_legacy_columns(df: pd.DataFrame) -> None:
    if LEGACY_COLUMNS.intersection(set(df.columns)):
        raise RuntimeError(
            "Legacy curve format detected. Migrate to canonical_tag curves."
        )


def validate_curve_columns(df: pd.DataFrame) -> None:
    if list(df.columns) != list(CURVE_COLUMNS):
        raise ValueError(
            "Invalid curve schema. Curves must use canonical_tag format only."
        )


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


def _fill_mid_price(row: pd.Series) -> pd.Series:
    if pd.notna(row.get("price_mid")):
        return row
    low = _to_numeric(row.get("price_low"))
    high = _to_numeric(row.get("price_high"))
    if low is not None and high is not None:
        row["price_mid"] = round((low + high) / 2.0)
    return row


def load_curves(path: Path | None = None) -> pd.DataFrame:
    curve_path = path or dataset_path("curves.csv")
    if not curve_path.exists():
        return pd.DataFrame(columns=list(CURVE_COLUMNS))
    df = pd.read_csv(curve_path)
    detect_legacy_columns(df)
    validate_curve_columns(df)
    df["canonical_tag"] = df["canonical_tag"].astype(str).str.strip()
    df["anchor_year"] = df["anchor_year"].apply(_to_int)
    df["km_bucket"] = df["km_bucket"].apply(_to_int)
    df["price_low"] = df["price_low"].apply(_to_int)
    df["price_mid"] = df["price_mid"].apply(_to_int)
    df["price_high"] = df["price_high"].apply(_to_int)
    df = df.apply(_fill_mid_price, axis=1)
    return df[list(CURVE_COLUMNS)].copy()


def save_curves(df: pd.DataFrame, path: Path | None = None) -> None:
    detect_legacy_columns(df)
    validate_curve_columns(df)
    curve_path = path or dataset_path("curves.csv")
    curve_path.parent.mkdir(parents=True, exist_ok=True)
    working = df[list(CURVE_COLUMNS)].copy()
    working = working.apply(_fill_mid_price, axis=1)
    working.to_csv(curve_path, index=False)
    append_audit_snapshot(working, curve_path)
    snapshot_curve_version(curve_path, source="save_curves")


def get_curve_points(
    curves_df: pd.DataFrame, canonical_tag: str, anchor_year: int
) -> List[Tuple[int, int]]:
    if curves_df.empty:
        return []
    subset = curves_df[
        (curves_df["canonical_tag"] == canonical_tag)
        & (curves_df["anchor_year"] == anchor_year)
    ].copy()
    subset = subset.dropna(subset=["km_bucket", "price_mid"])
    if subset.empty:
        return []
    subset["km_bucket"] = subset["km_bucket"].apply(_to_int)
    subset["price_mid"] = subset["price_mid"].apply(_to_int)
    subset = subset.dropna(subset=["km_bucket", "price_mid"])
    points = list(
        subset.sort_values("km_bucket")[["km_bucket", "price_mid"]].itertuples(
            index=False, name=None
        )
    )
    return [(int(km), int(price)) for km, price in points]


def interpolate_price_by_km(
    points: Iterable[Tuple[int, int]], km: float | int | None
) -> Optional[float]:
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
    canonical_tag: str,
    year: int | None,
    km: float | int | None,
) -> Optional[float]:
    if curves_df.empty or not canonical_tag or year is None or km is None:
        return None
    subset = curves_df[curves_df["canonical_tag"] == canonical_tag].copy()
    subset = subset.dropna(subset=["anchor_year"])
    if subset.empty:
        return None
    anchor_years = sorted({int(y) for y in subset["anchor_year"].dropna()})
    if not anchor_years:
        return None

    def _price_for_anchor(anchor_year: int) -> Optional[float]:
        points = get_curve_points(subset, canonical_tag, anchor_year)
        return interpolate_price_by_km(points, km)

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
