from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from shared.curves import CURVE_COLUMNS


REQUIRED_KM_BUCKETS = [30000, 60000, 100000, 150000, 200000]


@dataclass(frozen=True)
class ProposalMetadata:
    base_curve_tag: str
    anchor_years: list[int]
    active_rows_used: int
    active_rows_trimmed: int
    sold_rows_observed: int
    notes: str


def nearest_km_bucket(km_value: float, buckets: list[int] | None = None) -> int:
    bucket_list = buckets or REQUIRED_KM_BUCKETS
    return int(min(bucket_list, key=lambda bucket: abs(bucket - km_value)))


def _interpolate_quantiles(series: pd.Series, *, buckets: list[int]) -> pd.Series:
    working = series.astype(float).copy()
    working = working.reindex(buckets)
    working = working.interpolate(method="linear", limit_direction="both")
    working = working.ffill().bfill()
    return working


def _isotonic_fit(x_values: list[int], y_values: list[float], *, increasing: bool) -> list[int]:
    model = IsotonicRegression(increasing=increasing, out_of_bounds="clip")
    fitted = model.fit_transform(np.array(x_values, dtype=float), np.array(y_values, dtype=float))
    return [int(round(max(1.0, value))) for value in fitted.tolist()]


def _prepare_market_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    working = df.copy()
    working["year_numeric"] = pd.to_numeric(working.get("year_numeric"), errors="coerce")
    working["price_numeric"] = pd.to_numeric(working.get("price_numeric"), errors="coerce")
    working["odometer_numeric"] = pd.to_numeric(working.get("odometer_numeric"), errors="coerce")
    working = working.dropna(subset=["year_numeric", "price_numeric", "odometer_numeric"]).copy()
    if working.empty:
        return working
    working["year_numeric"] = working["year_numeric"].round().astype(int)
    working["km_bucket"] = working["odometer_numeric"].astype(float).apply(nearest_km_bucket)
    return working


def _trim_price_outliers(active_df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if active_df.empty:
        return active_df.copy(), 0
    trimmed_rows = 0
    working = active_df.copy()
    for group_column, min_group_size in [("km_bucket", 6), ("year_numeric", 8)]:
        kept_parts: list[pd.DataFrame] = []
        for _, subset in working.groupby(group_column, sort=True):
            if len(subset) < min_group_size:
                kept_parts.append(subset.copy())
                continue
            median_price = float(pd.to_numeric(subset["price_numeric"], errors="coerce").median())
            if median_price <= 0:
                kept_parts.append(subset.copy())
                continue
            lower_bound = median_price * 0.7
            upper_bound = median_price * 1.3
            kept = subset[
                pd.to_numeric(subset["price_numeric"], errors="coerce").between(lower_bound, upper_bound, inclusive="both")
            ].copy()
            if kept.empty:
                kept_parts.append(subset.copy())
                continue
            trimmed_rows += int(len(subset) - len(kept))
            kept_parts.append(kept)
        working = pd.concat(kept_parts, ignore_index=True) if kept_parts else working
    return working, trimmed_rows


def prepare_active_market_for_proposal(active_market_df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    prepared = _prepare_market_rows(active_market_df)
    return _trim_price_outliers(prepared)


def _windowed_active_rows(active_df: pd.DataFrame, anchor_year: int) -> pd.DataFrame:
    if active_df.empty:
        return pd.DataFrame()
    years = pd.to_numeric(active_df.get("year_numeric"), errors="coerce")
    if years.dropna().empty:
        return pd.DataFrame()
    for window in [1, 2, 3]:
        subset = active_df[years.between(anchor_year - window, anchor_year + window, inclusive="both").fillna(False)].copy()
        if len(subset) >= 12:
            return subset
    return active_df[years.between(anchor_year - 3, anchor_year + 3, inclusive="both").fillna(False)].copy()


def _propose_for_anchor_year(
    *,
    base_curve_tag: str,
    anchor_year: int,
    active_df: pd.DataFrame,
    buckets: list[int],
) -> pd.DataFrame:
    subset = _windowed_active_rows(active_df, anchor_year)
    if subset.empty:
        return pd.DataFrame(columns=list(CURVE_COLUMNS))

    grouped = subset.groupby("km_bucket")["price_numeric"]
    q35 = _interpolate_quantiles(grouped.quantile(0.35), buckets=buckets)
    q50 = _interpolate_quantiles(grouped.quantile(0.50), buckets=buckets)
    q65 = _interpolate_quantiles(grouped.quantile(0.65), buckets=buckets)

    mid_values = _isotonic_fit(buckets, q50.tolist(), increasing=False)
    low_seed = [min(mid, int(round(value))) for mid, value in zip(mid_values, q35.tolist())]
    high_seed = [max(mid, int(round(value))) for mid, value in zip(mid_values, q65.tolist())]

    low_values = _isotonic_fit(buckets, low_seed, increasing=False)
    high_values = _isotonic_fit(buckets, high_seed, increasing=False)
    low_values = [min(low, mid) for low, mid in zip(low_values, mid_values)]
    high_values = [max(high, mid) for high, mid in zip(high_values, mid_values)]

    rows: list[dict[str, int | str]] = []
    for km_bucket, price_low, price_mid, price_high in zip(buckets, low_values, mid_values, high_values):
        rows.append(
            {
                "canonical_tag": base_curve_tag,
                "anchor_year": int(anchor_year),
                "km_bucket": int(km_bucket),
                "price_low": int(max(1, price_low)),
                "price_mid": int(max(1, price_mid)),
                "price_high": int(max(1, price_high)),
            }
        )
    return pd.DataFrame(rows, columns=list(CURVE_COLUMNS))


def _enforce_year_monotonicity(proposed_df: pd.DataFrame) -> pd.DataFrame:
    if proposed_df.empty:
        return proposed_df
    working = proposed_df.copy().sort_values(["km_bucket", "anchor_year"]).reset_index(drop=True)
    for km_bucket, subset in working.groupby("km_bucket", sort=True):
        years = subset["anchor_year"].astype(int).tolist()
        for price_column in ["price_low", "price_mid", "price_high"]:
            fitted = _isotonic_fit(years, subset[price_column].astype(float).tolist(), increasing=True)
            working.loc[subset.index, price_column] = fitted
    working["price_low"] = np.minimum(working["price_low"], working["price_mid"]).astype(int)
    working["price_high"] = np.maximum(working["price_high"], working["price_mid"]).astype(int)
    return working[list(CURVE_COLUMNS)].sort_values(["anchor_year", "km_bucket"]).reset_index(drop=True)


def propose_curve_from_evidence(
    *,
    base_curve_tag: str,
    active_market_df: pd.DataFrame,
    sold_df: pd.DataFrame | None = None,
    anchor_years: list[int] | None = None,
    buckets: list[int] | None = None,
) -> tuple[pd.DataFrame, ProposalMetadata]:
    bucket_list = buckets or REQUIRED_KM_BUCKETS
    active_rows, trimmed_rows = prepare_active_market_for_proposal(active_market_df)
    sold_rows = _prepare_market_rows(sold_df.copy()) if sold_df is not None and not sold_df.empty else pd.DataFrame()

    if anchor_years:
        anchors = sorted({int(value) for value in anchor_years})
    else:
        available_years = pd.to_numeric(active_rows.get("year_numeric"), errors="coerce").dropna().astype(int)
        if available_years.empty:
            anchors = [2020]
        else:
            year_min = int(available_years.min())
            year_max = int(available_years.max())
            if year_min == year_max:
                anchors = [year_min]
            else:
                anchors = sorted({year_min, int(round((year_min + year_max) / 2.0)), year_max})

    proposal_frames: list[pd.DataFrame] = []
    for anchor_year in anchors:
        frame = _propose_for_anchor_year(
            base_curve_tag=base_curve_tag,
            anchor_year=anchor_year,
            active_df=active_rows,
            buckets=bucket_list,
        )
        if not frame.empty:
            proposal_frames.append(frame)

    if proposal_frames:
        combined = pd.concat(proposal_frames, ignore_index=True)
        combined = _enforce_year_monotonicity(combined)
    else:
        combined = pd.DataFrame(columns=list(CURVE_COLUMNS))

    notes = (
        "Deterministic proposal built from recent Autotrader market listing prices. "
        "Sold rows were observed for coverage only and do not drive the proposed prices. "
        "Extreme recent-market price outliers were trimmed before fitting."
    )
    metadata = ProposalMetadata(
        base_curve_tag=base_curve_tag,
        anchor_years=anchors,
        active_rows_used=int(len(active_rows)),
        active_rows_trimmed=int(trimmed_rows),
        sold_rows_observed=int(len(sold_rows)),
        notes=notes,
    )
    return combined, metadata
