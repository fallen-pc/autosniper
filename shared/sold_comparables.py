"""Comparable-sale selection shared by valuation surfaces."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ComparableStats:
    count: int
    median: float | None
    mean: float | None
    minimum: float | None
    maximum: float | None
    method: str
    km_min: float | None
    km_max: float | None
    km_distance_median: float | None


def _empty_stats() -> ComparableStats:
    return ComparableStats(0, None, None, None, None, "none", None, None, None)


def select_km_aware_comparables(
    sold_rows: pd.DataFrame,
    target_km: float | None,
    *,
    min_samples: int = 3,
    preferred_window_km: float = 50_000,
    expanded_window_km: float = 100_000,
    max_samples: int = 20,
) -> tuple[pd.DataFrame, ComparableStats]:
    """Choose the nearest useful sold rows, falling back to the supplied pool."""
    if sold_rows is None or sold_rows.empty:
        return pd.DataFrame(), _empty_stats()

    working = sold_rows.copy()
    working["price_numeric"] = pd.to_numeric(working.get("price_numeric"), errors="coerce")
    working["odometer_numeric"] = pd.to_numeric(working.get("odometer_numeric"), errors="coerce")
    working = working.dropna(subset=["price_numeric"])
    working = working[working["price_numeric"] > 0]
    if working.empty:
        return working, _empty_stats()

    selected = working
    method = "tag_year_fallback"
    target = pd.to_numeric(pd.Series([target_km]), errors="coerce").iloc[0]
    if pd.notna(target):
        with_km = working.dropna(subset=["odometer_numeric"]).copy()
        with_km["km_distance"] = (with_km["odometer_numeric"] - float(target)).abs()
        preferred = with_km[with_km["km_distance"] <= preferred_window_km]
        expanded = with_km[with_km["km_distance"] <= expanded_window_km]
        if len(preferred) >= min_samples:
            selected = preferred.nsmallest(max_samples, "km_distance")
            method = "nearest_km"
        elif len(expanded) >= min_samples:
            selected = expanded.nsmallest(max_samples, "km_distance")
            method = "expanded_km"

    prices = selected["price_numeric"]
    km_values = selected["odometer_numeric"].dropna()
    distances = selected.get("km_distance", pd.Series(dtype="float64")).dropna()
    stats = ComparableStats(
        count=int(len(selected)),
        median=float(prices.median()),
        mean=float(prices.mean()),
        minimum=float(prices.min()),
        maximum=float(prices.max()),
        method=method,
        km_min=float(km_values.min()) if not km_values.empty else None,
        km_max=float(km_values.max()) if not km_values.empty else None,
        km_distance_median=float(distances.median()) if not distances.empty else None,
    )
    return selected.drop(columns=["km_distance"], errors="ignore"), stats
