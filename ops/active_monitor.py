from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from scripts.ai_listing_valuation import load_cached_results, run_curve_listing_analysis, upsert_manual_result_row
from shared.canonical_tagging import is_canonical_eligible
from shared.comps_engine import parse_currency, parse_numeric
from shared.curves import interpolate_base_by_year, list_curve_tags, load_curves, resolve_curve_canonical_tag
from shared.data_loader import dataset_path


ACTIVE_RESTRICTED_PATH = dataset_path("active_vehicle_details_restricted.csv")
ACTIVE_LIVE_PATH = dataset_path("active_vehicle_details.csv")
GROUP_MAP_PATH = dataset_path("restricted_group_map.csv")
SOLD_RESTRICTED_PATH = dataset_path("sold_cars_restricted.csv")
NORMALIZED_CONDITIONS_PATH = Path("CSV_data/reports/normalized_conditions.csv")
COMPLETED_STATUSES = {"sold", "referred", "canceled", "cancelled", "closed"}


def _safe_int(value: object) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _load_normalized_conditions() -> pd.DataFrame:
    if not NORMALIZED_CONDITIONS_PATH.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(NORMALIZED_CONDITIONS_PATH)
    except Exception:
        return pd.DataFrame()
    if "url" not in df.columns or "component_normalized" not in df.columns:
        return pd.DataFrame()
    df["url"] = df["url"].astype(str).str.strip()
    df["component_normalized"] = df["component_normalized"].astype(str).str.strip()
    df = df[df["component_normalized"] != ""]
    return df


def _merge_live_fields(active_df: pd.DataFrame, live_df: pd.DataFrame) -> pd.DataFrame:
    if active_df.empty or live_df.empty:
        return active_df
    live_fields = ["url", "price", "bids", "time_remaining_or_date_sold", "location", "status"]
    live_subset = live_df[[field for field in live_fields if field in live_df.columns]].copy()
    merged = active_df.merge(live_subset, on="url", how="left", suffixes=("", "_live"))
    for field in ("price", "bids", "time_remaining_or_date_sold", "location", "status"):
        live_field = f"{field}_live"
        if live_field in merged.columns:
            if field in merged.columns:
                merged[field] = merged[live_field].combine_first(merged[field])
            else:
                merged[field] = merged[live_field]
            merged = merged.drop(columns=[live_field])
    return merged


def _attach_group_tags(df: pd.DataFrame, group_map_df: pd.DataFrame, source: str) -> pd.DataFrame:
    if df.empty or group_map_df.empty:
        return df
    groups = group_map_df[group_map_df["source"] == source][["url", "canonical_tag", "reason_code"]]
    groups = groups.rename(columns={"reason_code": "canonical_reason"}).drop_duplicates("url")
    return df.merge(groups, on="url", how="left")


def _attach_normalized_conditions(active_df: pd.DataFrame, sold_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalized_df = _load_normalized_conditions()
    if normalized_df.empty:
        return active_df, sold_df
    grouped = (
        normalized_df.groupby("url")["component_normalized"]
        .apply(lambda series: "\n".join(dict.fromkeys(series.tolist())))
        .to_dict()
    )
    if not active_df.empty and "url" in active_df.columns:
        active_df = active_df.copy()
        active_df["normalized_condition_text"] = active_df["url"].map(grouped).fillna("")
    if not sold_df.empty and "url" in sold_df.columns:
        sold_df = sold_df.copy()
        sold_df["normalized_condition_text"] = sold_df["url"].map(grouped).fillna("")
    return active_df, sold_df


def _curve_band_maps(curves_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    year_band = (
        curves_df.dropna(subset=["canonical_tag", "anchor_year"])
        .assign(anchor_year=lambda frame: pd.to_numeric(frame["anchor_year"], errors="coerce"))
        .dropna(subset=["anchor_year"])
        .groupby("canonical_tag")["anchor_year"]
        .agg(["min", "max"])
        .rename(columns={"min": "min_year", "max": "max_year"})
    )
    km_band = (
        curves_df.dropna(subset=["canonical_tag", "km_bucket"])
        .assign(km_bucket=lambda frame: pd.to_numeric(frame["km_bucket"], errors="coerce"))
        .dropna(subset=["km_bucket"])
        .groupby("canonical_tag")["km_bucket"]
        .agg(["min", "max"])
        .rename(columns={"min": "min_km", "max": "max_km"})
    )
    return year_band, km_band


def _prepare_active_scope() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    curves_df = load_curves()
    active_df = _load_csv(ACTIVE_RESTRICTED_PATH)
    live_df = _load_csv(ACTIVE_LIVE_PATH)
    group_map_df = _load_csv(GROUP_MAP_PATH)
    sold_df = _load_csv(SOLD_RESTRICTED_PATH)

    if active_df.empty:
        return pd.DataFrame(), sold_df, curves_df

    active_df["url"] = active_df["url"].astype(str).str.strip()
    if not live_df.empty and "url" in live_df.columns:
        live_df["url"] = live_df["url"].astype(str).str.strip()
    if not group_map_df.empty and "url" in group_map_df.columns:
        group_map_df["url"] = group_map_df["url"].astype(str).str.strip()
    if not sold_df.empty and "url" in sold_df.columns:
        sold_df["url"] = sold_df["url"].astype(str).str.strip()

    active_df = _attach_group_tags(active_df, group_map_df, "active")
    sold_df = _attach_group_tags(sold_df, group_map_df, "sold")
    active_df = _merge_live_fields(active_df, live_df)
    active_df, sold_df = _attach_normalized_conditions(active_df, sold_df)
    if "status" in active_df.columns:
        statuses = active_df["status"].astype(str).str.lower().str.strip()
        active_df = active_df[~statuses.isin(COMPLETED_STATUSES)].copy()

    active_df["odometer_numeric"] = active_df["odometer_reading"].apply(parse_numeric)
    active_df["price_numeric"] = active_df["price"].apply(parse_currency) if "price" in active_df.columns else None
    active_df["year_int"] = active_df["year"].apply(_safe_int)
    if "canonical_tag" not in active_df.columns:
        active_df["canonical_tag"] = ""
    active_df["canonical_tag"] = active_df["canonical_tag"].fillna("").astype(str).str.strip()
    active_df["curve_tag"] = active_df["canonical_tag"].apply(resolve_curve_canonical_tag)
    active_df["canonical_eligible"] = active_df.apply(
        lambda row: is_canonical_eligible(row.get("canonical_tag"), row.get("canonical_reason")),
        axis=1,
    )

    allowed_tags = list_curve_tags(curves_df)
    year_band, km_band = _curve_band_maps(curves_df)
    active_df = active_df.merge(year_band, left_on="curve_tag", right_index=True, how="left")
    active_df = active_df.merge(km_band, left_on="curve_tag", right_index=True, how="left")
    active_df["tag_in_curves"] = active_df["canonical_tag"].isin(allowed_tags)
    active_df["year_in_range"] = (
        active_df["year_int"].notna()
        & active_df["min_year"].notna()
        & active_df["max_year"].notna()
        & (active_df["year_int"] >= active_df["min_year"])
        & (active_df["year_int"] <= active_df["max_year"])
    )
    active_df["km_in_range"] = (
        active_df["odometer_numeric"].notna()
        & active_df["min_km"].notna()
        & active_df["max_km"].notna()
        & (active_df["odometer_numeric"] >= active_df["min_km"])
        & (active_df["odometer_numeric"] <= active_df["max_km"])
    )
    active_df["curve_coverage"] = (
        active_df["tag_in_curves"]
        & active_df["canonical_eligible"]
        & active_df["year_in_range"]
        & active_df["km_in_range"]
    )
    active_df = active_df[active_df["curve_coverage"]].copy()

    if not sold_df.empty:
        sold_df["price_numeric"] = sold_df["price"].apply(parse_currency)
        sold_df["year_int"] = sold_df["year"].apply(_safe_int)
        if "canonical_tag" not in sold_df.columns:
            sold_df["canonical_tag"] = ""
        sold_df["canonical_tag"] = sold_df["canonical_tag"].fillna("").astype(str).str.strip()
        sold_df["curve_tag"] = sold_df["canonical_tag"].apply(resolve_curve_canonical_tag)
        sold_df = sold_df[sold_df["canonical_tag"].isin(allowed_tags)].copy()

    return active_df, sold_df, curves_df


def _prepare_all_active_rows() -> pd.DataFrame:
    active_df = _load_csv(ACTIVE_RESTRICTED_PATH)
    live_df = _load_csv(ACTIVE_LIVE_PATH)
    group_map_df = _load_csv(GROUP_MAP_PATH)
    if active_df.empty:
        return active_df
    active_df["url"] = active_df["url"].astype(str).str.strip()
    if not live_df.empty and "url" in live_df.columns:
        live_df["url"] = live_df["url"].astype(str).str.strip()
    if not group_map_df.empty and "url" in group_map_df.columns:
        group_map_df["url"] = group_map_df["url"].astype(str).str.strip()
    active_df = _attach_group_tags(active_df, group_map_df, "active")
    active_df = _merge_live_fields(active_df, live_df)
    if "status" in active_df.columns:
        statuses = active_df["status"].astype(str).str.lower().str.strip()
        active_df = active_df[~statuses.isin(COMPLETED_STATUSES)].copy()
    return active_df


def _build_sold_stats(sold_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if sold_df.empty:
        empty = pd.DataFrame(columns=["comps_count", "comps_median", "comps_mean", "comps_min", "comps_max"])
        return empty, empty
    sold_stats_group = (
        sold_df.dropna(subset=["curve_tag", "price_numeric"])
        .groupby("curve_tag")["price_numeric"]
        .agg(["count", "median", "mean", "min", "max"])
        .rename(
            columns={
                "count": "comps_count",
                "median": "comps_median",
                "mean": "comps_mean",
                "min": "comps_min",
                "max": "comps_max",
            }
        )
    )
    sold_stats_year = (
        sold_df.dropna(subset=["curve_tag", "price_numeric", "year_int"])
        .groupby(["curve_tag", "year_int"])["price_numeric"]
        .agg(["count", "median", "mean", "min", "max"])
        .rename(
            columns={
                "count": "comps_count",
                "median": "comps_median",
                "mean": "comps_mean",
                "min": "comps_min",
                "max": "comps_max",
            }
        )
    )
    return sold_stats_group, sold_stats_year


def _stale_or_missing_urls(active_df: pd.DataFrame, stale_minutes: int) -> set[str]:
    cached_df = load_cached_results()
    active_urls = set(active_df["url"].dropna().astype(str).tolist())
    if cached_df.empty or "url" not in cached_df.columns:
        return active_urls
    cached_df = cached_df[cached_df["url"].isin(active_urls)].copy()
    stale_urls = active_urls - set(cached_df["url"].dropna().astype(str).tolist())
    if "analysis_timestamp" not in cached_df.columns:
        return active_urls
    cached_df["analysis_timestamp"] = pd.to_datetime(cached_df["analysis_timestamp"], errors="coerce", utc=True)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    stale_rows = cached_df[cached_df["analysis_timestamp"].isna() | (cached_df["analysis_timestamp"] < cutoff)]
    stale_urls.update(stale_rows["url"].dropna().astype(str).tolist())
    return stale_urls


def _upsert_not_covered_result(row: pd.Series, reason: str) -> None:
    current_bid = row.get("price")
    payload = {
        "url": row.get("url"),
        "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
        "analysis_context": "active",
        "resale_low": None,
        "resale_mid": None,
        "resale_high": None,
        "net_profit_mid": None,
        "net_profit_worst": None,
        "fees_estimate": None,
        "transport_estimate": None,
        "rego_estimate": None,
        "prep_estimate": None,
        "confidence": 0.0,
        "risk_flags": "NO_CURVE",
        "computed_verdict": "Not Covered",
        "no_edge": True,
        "edge_note": reason,
        "edge_buffer": None,
        "carsales_price_estimate": None,
        "carsales_price_range": None,
        "recommended_max_bid": None,
        "expected_profit": None,
        "profit_margin_percent": None,
        "score_out_of_10": None,
        "confidence_notes": reason,
        "is_top_buy": False,
        "top_buy_badge": None,
        "top_buy_failed_reasons": "[]",
        "top_buy_passed_reasons": "[]",
        "current_bid": current_bid,
        "current_bid_numeric": parse_currency(current_bid) if current_bid is not None else None,
        "bids_observed": row.get("bids"),
        "time_remaining_observed": row.get("time_remaining_or_date_sold"),
    }
    upsert_manual_result_row(payload)


def _mark_dropped_coverage_urls(
    all_active_df: pd.DataFrame,
    covered_active_df: pd.DataFrame,
    target_urls: set[str],
) -> int:
    if all_active_df.empty or not target_urls:
        return 0
    all_urls = set(all_active_df["url"].dropna().astype(str).tolist())
    covered_urls = set(covered_active_df["url"].dropna().astype(str).tolist()) if not covered_active_df.empty else set()
    dropped_urls = (target_urls & all_urls) - covered_urls
    if not dropped_urls:
        return 0

    rows = all_active_df[all_active_df["url"].isin(dropped_urls)].copy()
    if rows.empty:
        return 0

    count = 0
    for _, row in rows.iterrows():
        canonical_tag = str(row.get("canonical_tag") or "").strip()
        canonical_reason = str(row.get("canonical_reason") or "").strip()
        if canonical_tag and not is_canonical_eligible(canonical_tag, canonical_reason):
            reason = f"Listing is no longer curve-covered: {canonical_reason or 'canonical tag is not eligible.'}"
        else:
            reason = "Listing is no longer curve-covered due to missing curve or year/km range."
        _upsert_not_covered_result(row, reason)
        count += 1
    return count


def revalue_active_listings(
    *,
    target_urls: Iterable[str] | None = None,
    stale_minutes: int = 60,
    force_refresh: bool = False,
) -> dict[str, object]:
    all_active_df = _prepare_all_active_rows()
    active_df, sold_df, curves_df = _prepare_active_scope()
    if all_active_df.empty and active_df.empty:
        return {"evaluated": 0, "urls": []}

    sold_stats_group, sold_stats_year = _build_sold_stats(sold_df)
    if target_urls is None:
        urls_to_process = _stale_or_missing_urls(active_df, stale_minutes) if not active_df.empty else set()
    else:
        urls_to_process = {str(url).strip() for url in target_urls if str(url).strip()}
        if not active_df.empty:
            urls_to_process |= _stale_or_missing_urls(active_df, stale_minutes)
    if not urls_to_process:
        return {"evaluated": 0, "urls": []}

    dropped_count = _mark_dropped_coverage_urls(all_active_df, active_df, urls_to_process)

    scoped_df = active_df[active_df["url"].isin(urls_to_process)].copy()
    evaluated_urls: list[str] = []
    for _, row in scoped_df.iterrows():
        curve_key = resolve_curve_canonical_tag(row.get("canonical_tag"))
        if not curve_key:
            continue
        year_val = _safe_int(row.get("year"))
        odo_val = row.get("odometer_numeric")
        base_estimate = interpolate_base_by_year(curves_df, curve_key, year_val, odo_val)
        stats = None
        if year_val is not None and not sold_stats_year.empty and (curve_key, year_val) in sold_stats_year.index:
            stats = sold_stats_year.loc[(curve_key, year_val)]
        elif not sold_stats_group.empty and curve_key in sold_stats_group.index:
            stats = sold_stats_group.loc[curve_key]
        comps_count = int(stats["comps_count"]) if stats is not None else 0
        comps_median = float(stats["comps_median"]) if stats is not None else None
        run_curve_listing_analysis(
            row,
            base_estimate,
            comps_median=comps_median,
            comps_count=comps_count,
            analysis_context="active",
            carsales_estimate=base_estimate,
            listings_cluster_ok=bool(comps_count >= 3),
            force_refresh=force_refresh,
        )
        evaluated_urls.append(str(row.get("url")))
    return {
        "evaluated": len(evaluated_urls) + dropped_count,
        "urls": evaluated_urls,
        "dropped_coverage": dropped_count,
    }


def diff_changed_listing_urls(before_df: pd.DataFrame, after_df: pd.DataFrame) -> set[str]:
    if after_df.empty or "url" not in after_df.columns:
        return set()
    after = after_df.copy()
    after["url"] = after["url"].astype(str).str.strip()
    if before_df.empty or "url" not in before_df.columns:
        return set(after["url"].tolist())
    before = before_df.copy()
    before["url"] = before["url"].astype(str).str.strip()
    compare_columns = [column for column in ("price", "bids", "time_remaining_or_date_sold", "status") if column in after.columns or column in before.columns]
    before = before[["url"] + [column for column in compare_columns if column in before.columns]].drop_duplicates("url")
    after = after[["url"] + [column for column in compare_columns if column in after.columns]].drop_duplicates("url")
    merged = after.merge(before, on="url", how="outer", suffixes=("_after", "_before"), indicator=True)
    changed_urls: set[str] = set()
    for _, row in merged.iterrows():
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        if row.get("_merge") != "both":
            changed_urls.add(url)
            continue
        for column in compare_columns:
            before_val = row.get(f"{column}_before")
            after_val = row.get(f"{column}_after")
            before_text = "" if pd.isna(before_val) else str(before_val).strip()
            after_text = "" if pd.isna(after_val) else str(after_val).strip()
            if before_text != after_text:
                changed_urls.add(url)
                break
    return changed_urls


def load_live_active_df() -> pd.DataFrame:
    df = _load_csv(ACTIVE_LIVE_PATH)
    if df.empty:
        return df
    if "url" in df.columns:
        df["url"] = df["url"].astype(str).str.strip()
    if "status" in df.columns:
        statuses = df["status"].astype(str).str.lower().str.strip()
        df = df[~statuses.isin({"sold", "referred", "canceled", "cancelled", "closed"})].copy()
    return df


def active_urls_from_frame(df: pd.DataFrame) -> list[str]:
    if df.empty or "url" not in df.columns:
        return []
    urls = df["url"].dropna().astype(str).tolist()
    return sorted({url for url in urls if url.startswith("http")})
