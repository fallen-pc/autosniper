"""Curve storage and interpolation helpers."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from shared.audit import append_audit_snapshot
from shared.curve_groups_v2 import load_curve_groups_v2, resolve_base_curve_tag
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
HIGH_KM_COVERAGE_BUFFER = 10_000

LEGACY_COLUMNS = {"group_id", "series", "km_anchor", "price_median"}
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CURVE_ALIASES_PATH = CONFIG_DIR / "curve_aliases.csv"
CURVE_ALIAS_COLUMNS: Sequence[str] = ("canonical_tag", "base_curve")


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


@lru_cache(maxsize=1)
def load_curve_aliases(path: Path | None = None) -> dict[str, str]:
    alias_path = path or CURVE_ALIASES_PATH
    if not alias_path.exists():
        return {}
    try:
        alias_df = pd.read_csv(alias_path)
    except (ValueError, pd.errors.EmptyDataError):
        return {}

    missing = [column for column in CURVE_ALIAS_COLUMNS if column not in alias_df.columns]
    if missing:
        raise ValueError(
            "Invalid curve alias schema. Missing columns: " + ", ".join(sorted(missing))
        )

    aliases: dict[str, str] = {}
    for _, row in alias_df.iterrows():
        alias_tag = str(row.get("canonical_tag", "")).strip()
        base_curve = str(row.get("base_curve", "")).strip()
        if not alias_tag or not base_curve or alias_tag == base_curve:
            continue
        aliases[alias_tag] = base_curve
    return aliases


@lru_cache(maxsize=1)
def load_saved_curve_tags(path: Path | None = None) -> set[str]:
    curve_path = path or dataset_path("curves.csv")
    if not curve_path.exists():
        return set()
    try:
        df = pd.read_csv(curve_path, usecols=["canonical_tag"])
    except Exception:
        return set()
    return {
        str(value).strip()
        for value in df.get("canonical_tag", pd.Series(dtype="object")).dropna().astype(str).tolist()
        if str(value).strip()
    }


def resolve_curve_canonical_tag(
    canonical_tag: object,
    aliases: Mapping[str, str] | None = None,
    curves_df: pd.DataFrame | None = None,
) -> str:
    original = str(canonical_tag or "").strip()
    resolved = original
    if not resolved:
        return ""

    alias_map = dict(aliases) if aliases is not None else load_curve_aliases()
    seen: set[str] = set()
    while resolved in alias_map and resolved not in seen:
        seen.add(resolved)
        next_tag = str(alias_map.get(resolved, "")).strip()
        if not next_tag:
            break
        resolved = next_tag

    groups_df = load_curve_groups_v2()
    if groups_df.empty:
        return resolved

    candidate_base_tags = []
    for tag_value in (original, resolved):
        candidate = resolve_base_curve_tag(tag_value, groups_df)
        if candidate and candidate not in candidate_base_tags:
            candidate_base_tags.append(candidate)

    if not candidate_base_tags:
        return resolved

    if curves_df is not None and not curves_df.empty and "canonical_tag" in curves_df.columns:
        available_tags = {
            str(value).strip()
            for value in curves_df["canonical_tag"].dropna().astype(str).tolist()
            if str(value).strip()
        }
    else:
        available_tags = load_saved_curve_tags()

    for candidate in candidate_base_tags:
        if candidate in available_tags:
            return candidate
    return resolved


def list_curve_tags(curves_df: pd.DataFrame | None, *, include_aliases: bool = True) -> set[str]:
    if curves_df is None or curves_df.empty or "canonical_tag" not in curves_df.columns:
        return set()

    tags = {
        str(tag).strip()
        for tag in curves_df["canonical_tag"].dropna().astype(str).tolist()
        if str(tag).strip()
    }
    if not include_aliases or not tags:
        return tags

    aliases = load_curve_aliases()
    for alias_tag, base_curve in aliases.items():
        if resolve_curve_canonical_tag(base_curve, aliases, curves_df) in tags:
            tags.add(alias_tag)
    groups_df = load_curve_groups_v2()
    if not groups_df.empty:
        for _, row in groups_df.iterrows():
            match_tag = str(row.get("match_tag", "")).strip()
            base_curve = str(row.get("base_curve_tag", "")).strip()
            if match_tag and base_curve and resolve_curve_canonical_tag(base_curve, aliases, curves_df) in tags:
                tags.add(match_tag)
    return tags


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
    load_saved_curve_tags.cache_clear()
    append_audit_snapshot(working, curve_path)
    snapshot_curve_version(curve_path, source="save_curves")


def get_curve_points(
    curves_df: pd.DataFrame, canonical_tag: str, anchor_year: int
) -> List[Tuple[int, int]]:
    if curves_df.empty:
        return []
    curve_tag = resolve_curve_canonical_tag(canonical_tag, curves_df=curves_df)
    if not curve_tag:
        return []
    subset = curves_df[
        (curves_df["canonical_tag"] == curve_tag)
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


def km_within_curve_coverage(
    km: float | int | None,
    min_km: float | int | None,
    max_km: float | int | None,
    *,
    high_km_buffer: float | int = HIGH_KM_COVERAGE_BUFFER,
) -> bool:
    if km is None or min_km is None or max_km is None:
        return False
    return float(min_km) <= float(km) <= float(max_km) + float(high_km_buffer)


def interpolate_base_by_year(
    curves_df: pd.DataFrame,
    canonical_tag: str,
    year: int | None,
    km: float | int | None,
) -> Optional[float]:
    curve_tag = resolve_curve_canonical_tag(canonical_tag, curves_df=curves_df)
    if curves_df.empty or not curve_tag or year is None or km is None:
        return None
    subset = curves_df[curves_df["canonical_tag"] == curve_tag].copy()
    subset = subset.dropna(subset=["anchor_year"])
    if subset.empty:
        return None
    anchor_years = sorted({int(y) for y in subset["anchor_year"].dropna()})
    if not anchor_years:
        return None

    def _price_for_anchor(anchor_year: int) -> Optional[float]:
        points = get_curve_points(subset, curve_tag, anchor_year)
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
