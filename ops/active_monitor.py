from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
import logging
import os
import re

import pandas as pd

from scripts.ai_listing_valuation import (
    AI_RESULTS_PATH,
    REQUIRED_COLUMNS,
    _valuation_input_hash,
    load_cached_results,
    run_curve_listing_analysis,
    upsert_manual_result_row,
)
from scripts.atomic_csv import write_dataframe_csv_atomic
from scripts.process_curve_candidates import DEFAULT_AUTOTRADER_SOURCE, load_autotrader_market
from shared.canonical_tagging import UNCLASSIFIED, is_canonical_eligible
from shared.comps_engine import parse_currency, parse_numeric
from shared.csv_utils import CSV_READ_ERRORS
from shared.curves import interpolate_base_by_year, list_curve_tags, load_curves, resolve_curve_canonical_tag
from shared.data_loader import dataset_path
from shared.location_utils import extract_state
from shared.repair_pricing import assess_repairs, repair_fragments_to_records
from shared.repair_review import append_live_review_items

logger = logging.getLogger(__name__)

ACTIVE_RESTRICTED_PATH = dataset_path("active_vehicle_details_restricted.csv")
ACTIVE_LIVE_PATH = dataset_path("active_vehicle_details.csv")
GROUP_MAP_PATH = dataset_path("restricted_group_map.csv")
SOLD_RESTRICTED_PATH = dataset_path("sold_cars_restricted.csv")
NORMALIZED_CONDITIONS_PATH = Path("CSV_data/reports/normalized_conditions.csv")
EXTERNAL_AUCTION_MATCHES_FILENAME = "external_auction_curve_matches.csv"
EXTERNAL_AUCTION_LINKS_FILENAME = "external_auction_links.csv"
COMPLETED_STATUSES = {"sold", "referred", "canceled", "cancelled", "closed"}
WOVR_PATTERN = re.compile(
    r"\bwovr\b|wovr[-\s]*(?:inspected|repairable|statutory)|write[-\s]?off",
    re.IGNORECASE,
)


def _safe_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def _norm_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _token_match(left: object, right: object) -> bool:
    left_key = _norm_key(left)
    right_key = _norm_key(right)
    if not left_key or not right_key:
        return True
    return left_key == right_key or left_key in right_key or right_key in left_key


def _fuel_match(left: object, right: object) -> bool:
    def _norm_fuel(value: object) -> str:
        key = _norm_key(value)
        if key in {"petrol", "unleaded", "unleadedpetrol", "premium"}:
            return "petrol"
        return key

    return _token_match(_norm_fuel(left), _norm_fuel(right))


def _trans_match(left: object, right: object) -> bool:
    def _norm_trans(value: object) -> str:
        key = _norm_key(value)
        if key in {"auto", "automatic", "cvt", "sportsautomatic", "sptsauto"}:
            return "auto"
        if key == "manual":
            return "manual"
        return key

    return _token_match(_norm_trans(left), _norm_trans(right))


def _body_match(left: object, right: object) -> bool:
    def _norm_body(value: object) -> str:
        key = _norm_key(value)
        if key in {"suv", "wagon", "stationwagon", "crossover"}:
            return "suv_wagon"
        if key in {"hatch", "hatchback"}:
            return "hatchback"
        return key

    return _token_match(_norm_body(left), _norm_body(right))


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


def _external_auction_matches_path() -> Path:
    output_dir = Path(os.getenv("AUTOSNIPER_EXTERNAL_AUCTIONS_OUTPUT_DIR") or "output/external_auction_scrape/daily")
    return output_dir / EXTERNAL_AUCTION_MATCHES_FILENAME


def _external_auction_links_path() -> Path:
    output_dir = Path(os.getenv("AUTOSNIPER_EXTERNAL_AUCTIONS_OUTPUT_DIR") or "output/external_auction_scrape/daily")
    return output_dir / EXTERNAL_AUCTION_LINKS_FILENAME


def _load_external_auction_active_rows() -> pd.DataFrame:
    df = _load_csv(_external_auction_matches_path())
    if df.empty:
        return df
    working = df.copy()
    for column in ("url", "year", "odometer_reading", "price", "status", "canonical_tag", "canonical_reason", "curve_tag"):
        if column not in working.columns:
            working[column] = ""
    working["url"] = working["url"].astype(str).str.strip()
    working = working[working["url"].str.startswith("http", na=False)].copy()
    if working.empty:
        return working
    if "source" not in working.columns:
        working["source"] = "external_auction"
    working["status"] = working["status"].fillna("").astype(str).str.strip()
    blank_status = working["status"].eq("")
    if blank_status.any():
        links_df = _load_csv(_external_auction_links_path())
        rediscovered_urls: set[str] = set()
        if not links_df.empty and "url" in links_df.columns:
            rediscovered_urls = set(
                links_df["url"]
                .fillna("")
                .astype(str)
                .str.strip()
                .loc[lambda values: values.str.startswith("http", na=False)]
            )
        rediscovered = working["url"].isin(rediscovered_urls)
        working = working[~blank_status | rediscovered].copy()
        working.loc[blank_status & rediscovered, "status"] = "Active"
    working["canonical_tag"] = working["canonical_tag"].fillna("").astype(str).str.strip()
    working["canonical_reason"] = working["canonical_reason"].fillna("").astype(str).str.strip()
    return working


def _load_normalized_conditions() -> pd.DataFrame:
    if not NORMALIZED_CONDITIONS_PATH.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(NORMALIZED_CONDITIONS_PATH)
    except CSV_READ_ERRORS as exc:
        logger.warning(
            "Unreadable normalized conditions %s (%s: %s); condition context will be missing.",
            NORMALIZED_CONDITIONS_PATH,
            type(exc).__name__,
            exc,
        )
        return pd.DataFrame()
    if "url" not in df.columns or "component_normalized" not in df.columns:
        return pd.DataFrame()
    df["url"] = df["url"].astype(str).str.strip()
    df["component_normalized"] = df["component_normalized"].astype(str).str.strip()
    df = df[df["component_normalized"] != ""]
    return df


def _listing_title(row: pd.Series) -> str:
    parts = [
        _safe_text(row.get("year")),
        _safe_text(row.get("make")),
        _safe_text(row.get("model")),
        _safe_text(row.get("variant")),
    ]
    return " ".join(part for part in parts if part)


def _condition_notes_for_review(row: pd.Series) -> str:
    normalized = _safe_text(row.get("normalized_condition_text"))
    if normalized:
        return normalized
    return _safe_text(row.get("general_condition"))


def _queue_unclassified_condition_fragments(row: pd.Series, *, source_file: str = "ACTIVE_MONITOR") -> int:
    condition_notes = _condition_notes_for_review(row)
    if not condition_notes:
        return 0
    assessment = assess_repairs(
        condition_notes,
        vehicle_value=parse_currency(row.get("resale_mid")) or parse_currency(row.get("carsales_price_estimate")),
    )
    records = repair_fragments_to_records(assessment)
    review_records = [
        record
        for record in records
        if _safe_text(record.get("status")) == "unclassified"
    ]
    if not review_records:
        return 0
    return append_live_review_items(
        review_records,
        vehicle=_listing_title(row),
        url=_safe_text(row.get("url")),
        condition_notes=condition_notes,
        source_file=source_file,
    )


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


def _exclude_shortlist_ineligible_rows(active_df: pd.DataFrame) -> pd.DataFrame:
    if active_df.empty:
        return active_df
    working = active_df.copy()
    if "status" in working.columns:
        statuses = working["status"].astype(str).str.lower().str.strip()
        working = working[~statuses.isin(COMPLETED_STATUSES)].copy()

    if "price" in working.columns:
        price_numeric = working["price"].apply(parse_currency)
        working = working[price_numeric.notna()].copy()
        if working.empty:
            return working

    columns = [col for col in ("variant", "url") if col in working.columns]
    if columns:
        combined = working[columns].fillna("").astype(str).agg(" ".join, axis=1)
        working = working[~combined.str.contains(WOVR_PATTERN, na=False)].copy()

    return working


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
    external_active_df = _load_external_auction_active_rows()
    live_df = _load_csv(ACTIVE_LIVE_PATH)
    group_map_df = _load_csv(GROUP_MAP_PATH)
    sold_df = _load_csv(SOLD_RESTRICTED_PATH)

    if active_df.empty and external_active_df.empty:
        return pd.DataFrame(), sold_df, curves_df

    if not active_df.empty:
        active_df["url"] = active_df["url"].astype(str).str.strip()
    if not live_df.empty and "url" in live_df.columns:
        live_df["url"] = live_df["url"].astype(str).str.strip()
    if not group_map_df.empty and "url" in group_map_df.columns:
        group_map_df["url"] = group_map_df["url"].astype(str).str.strip()
    if not sold_df.empty and "url" in sold_df.columns:
        sold_df["url"] = sold_df["url"].astype(str).str.strip()

    if not active_df.empty:
        active_df = _attach_group_tags(active_df, group_map_df, "active")
        active_df = _merge_live_fields(active_df, live_df)
    if not external_active_df.empty:
        active_df = pd.concat([active_df, external_active_df], ignore_index=True, sort=False)
    sold_df = _attach_group_tags(sold_df, group_map_df, "sold")
    active_df, sold_df = _attach_normalized_conditions(active_df, sold_df)
    active_df = _exclude_shortlist_ineligible_rows(active_df)

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
    active_df["tag_in_curves"] = active_df["curve_tag"].isin(allowed_tags)
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
        sold_df = sold_df[sold_df["curve_tag"].isin(allowed_tags)].copy()

    return active_df, sold_df, curves_df


def _prepare_all_active_rows() -> pd.DataFrame:
    active_df = _load_csv(ACTIVE_RESTRICTED_PATH)
    external_active_df = _load_external_auction_active_rows()
    live_df = _load_csv(ACTIVE_LIVE_PATH)
    group_map_df = _load_csv(GROUP_MAP_PATH)
    if active_df.empty and external_active_df.empty:
        return active_df
    if not active_df.empty:
        active_df["url"] = active_df["url"].astype(str).str.strip()
    if not live_df.empty and "url" in live_df.columns:
        live_df["url"] = live_df["url"].astype(str).str.strip()
    if not group_map_df.empty and "url" in group_map_df.columns:
        group_map_df["url"] = group_map_df["url"].astype(str).str.strip()
    if not active_df.empty:
        active_df = _attach_group_tags(active_df, group_map_df, "active")
        active_df = _merge_live_fields(active_df, live_df)
    if not external_active_df.empty:
        active_df = pd.concat([active_df, external_active_df], ignore_index=True, sort=False)
    active_df = _exclude_shortlist_ineligible_rows(active_df)
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


def _score_autotrader_matches(
    autotrader_df: pd.DataFrame,
    listing_row: pd.Series,
    curve_tag: str,
    *,
    limit: int = 50,
) -> pd.DataFrame:
    if autotrader_df.empty or not curve_tag:
        return pd.DataFrame()
    target_km = parse_numeric(listing_row.get("odometer_reading"))
    if target_km is None or target_km <= 0:
        return pd.DataFrame()

    listing_year = _safe_int(listing_row.get("year"))
    listing_state = extract_state(
        listing_row.get("location_state")
        or listing_row.get("rego_state")
        or listing_row.get("location")
    )
    listing_make = _norm_key(listing_row.get("make"))
    listing_fuel = listing_row.get("fuel_type")
    listing_trans = listing_row.get("transmission")
    listing_body = listing_row.get("body_type")

    rows: list[dict[str, object]] = []
    for _, candidate in autotrader_df.iterrows():
        if listing_make and _norm_key(candidate.get("make")) != listing_make:
            continue

        candidate_tag = str(candidate.get("canonical_tag") or "").strip()
        if candidate_tag == UNCLASSIFIED:
            continue
        candidate_tag = resolve_curve_canonical_tag(candidate_tag)
        if candidate_tag != curve_tag:
            continue

        if not _fuel_match(listing_fuel, candidate.get("fuel_type")):
            continue
        if not _trans_match(listing_trans, candidate.get("transmission")):
            continue
        if not _body_match(listing_body, candidate.get("body_type")):
            continue

        candidate_km = candidate.get("odometer_numeric")
        if candidate_km is None or pd.isna(candidate_km):
            continue
        km_diff = abs(float(candidate_km) - float(target_km))
        if km_diff > 100000:
            continue

        state_penalty = 0.0
        candidate_state = extract_state(candidate.get("location"))
        if listing_state and candidate_state and listing_state != candidate_state:
            state_penalty = 0.05

        age_penalty = 0.0
        candidate_year = candidate.get("year_numeric")
        if listing_year is not None and candidate_year is not None and not pd.isna(candidate_year):
            year_diff = abs(int(candidate_year) - listing_year)
            if year_diff == 1:
                age_penalty = 0.05
            elif year_diff > 1:
                age_penalty = 0.15

        row = candidate.to_dict()
        row["price_value"] = candidate.get("price_numeric")
        row["odometer_value"] = candidate.get("odometer_numeric")
        row["match_score"] = min(km_diff / 100000.0, 1.0) + state_penalty + age_penalty
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("match_score").head(max(1, int(limit))).reset_index(drop=True)


def _market_lifecycle_summary(matches: pd.DataFrame, curve_resale: object) -> dict[str, object]:
    resale_value = parse_currency(curve_resale)
    if matches.empty or resale_value is None or resale_value <= 0:
        return {
            "matched_count": 0,
            "fast_clear_count": 0,
            "stale_active_count": 0,
            "near_curve_count": 0,
        }

    now_ts = pd.Timestamp.now(tz="UTC")
    fast_clear_count = 0
    stale_active_count = 0
    near_curve_count = 0
    observed_days: list[float] = []
    near_prices: list[float] = []

    for _, match in matches.iterrows():
        price_value = parse_currency(match.get("price_value") or match.get("price_numeric") or match.get("price"))
        if price_value is None or price_value <= 0:
            continue
        if abs(price_value - resale_value) / resale_value > 0.10:
            continue
        near_curve_count += 1
        near_prices.append(float(price_value))

        first_seen = pd.to_datetime(match.get("first_seen"), errors="coerce", utc=True)
        last_seen = pd.to_datetime(match.get("last_seen"), errors="coerce", utc=True)
        sold_date = pd.to_datetime(match.get("sold_date"), errors="coerce", utc=True)
        status = str(match.get("status") or "").strip().lower()

        end_seen = sold_date if pd.notna(sold_date) else last_seen
        if pd.notna(first_seen) and pd.notna(end_seen):
            days_listed = max(0.0, (end_seen - first_seen).total_seconds() / 86400.0)
            observed_days.append(days_listed)
            if status in {"sold", "removed", "expired"} and days_listed <= 5:
                fast_clear_count += 1

        if status in {"", "active"} and pd.notna(first_seen):
            active_days = max(0.0, (now_ts - first_seen).total_seconds() / 86400.0)
            observed_days.append(active_days)
            if active_days >= 30:
                stale_active_count += 1

    return {
        "matched_count": int(len(matches)),
        "fast_clear_count": int(fast_clear_count),
        "stale_active_count": int(stale_active_count),
        "near_curve_count": int(near_curve_count),
        "median_days_listed": float(pd.Series(observed_days).median()) if observed_days else None,
        "median_near_curve_price": float(pd.Series(near_prices).median()) if near_prices else None,
    }


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


def _dropped_coverage_target_urls(
    all_active_df: pd.DataFrame,
    target_urls: Iterable[str] | None,
    stale_minutes: int,
) -> set[str]:
    if all_active_df.empty or "url" not in all_active_df.columns:
        return set()
    if target_urls is not None:
        return {str(url).strip() for url in target_urls if str(url).strip()}
    return _stale_or_missing_urls(all_active_df, stale_minutes)


def _upsert_not_covered_result(row: pd.Series, reason: str) -> None:
    current_bid = row.get("price")
    payload = {
        "url": row.get("url"),
        "year": row.get("year"),
        "make": row.get("make"),
        "model": row.get("model"),
        "variant": row.get("variant"),
        "location": row.get("location"),
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
        "verdict": "Not Covered",
        "action_label": "Review",
        "bid_status": "Not covered",
        "hard_max_safety": "No coverage",
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
        "current_bid": current_bid,
        "current_bid_numeric": parse_currency(current_bid) if current_bid is not None else None,
        "bids_observed": row.get("bids"),
        "time_remaining_observed": row.get("time_remaining_or_date_sold"),
        "valuation_input_hash": _valuation_input_hash(
            row,
            resale_mid=None,
            comps_median=None,
            comps_count=None,
            analysis_context="active",
            km_percentile=None,
            autotrader_median=None,
            carsales_estimate=None,
            listings_cluster_ok=False,
        ),
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


def _prune_inactive_cached_valuations(all_active_df: pd.DataFrame) -> int:
    cached_df = load_cached_results()
    if cached_df.empty or "url" not in cached_df.columns or "analysis_context" not in cached_df.columns:
        return 0
    active_urls = (
        set(all_active_df["url"].dropna().astype(str).str.strip().tolist())
        if not all_active_df.empty and "url" in all_active_df.columns
        else set()
    )
    if not active_urls:
        return 0
    url_text = cached_df["url"].astype(str).str.strip()
    active_context = cached_df["analysis_context"].astype(str).str.strip().str.lower().eq("active")
    stale_mask = active_context & ~url_text.isin(active_urls)
    stale_count = int(stale_mask.sum())
    if stale_count <= 0:
        return 0
    pruned = cached_df.loc[~stale_mask].copy()
    for column in REQUIRED_COLUMNS:
        if column not in pruned.columns:
            pruned[column] = None
    write_dataframe_csv_atomic(pruned, AI_RESULTS_PATH, index=False)
    return stale_count


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
    pruned_count = _prune_inactive_cached_valuations(all_active_df)
    autotrader_df = load_autotrader_market(DEFAULT_AUTOTRADER_SOURCE)

    sold_stats_group, sold_stats_year = _build_sold_stats(sold_df)
    if target_urls is None:
        urls_to_process = _stale_or_missing_urls(active_df, stale_minutes) if not active_df.empty else set()
    else:
        urls_to_process = {str(url).strip() for url in target_urls if str(url).strip()}
        if not active_df.empty:
            urls_to_process |= _stale_or_missing_urls(active_df, stale_minutes)
    if not urls_to_process:
        dropped_targets = _dropped_coverage_target_urls(all_active_df, target_urls, stale_minutes)
        dropped_count = _mark_dropped_coverage_urls(all_active_df, active_df, dropped_targets)
        return {
            "evaluated": dropped_count,
            "urls": [],
            "dropped_coverage": dropped_count,
            "pruned_inactive": pruned_count,
        }

    dropped_targets = urls_to_process | _dropped_coverage_target_urls(all_active_df, target_urls, stale_minutes)
    dropped_count = _mark_dropped_coverage_urls(all_active_df, active_df, dropped_targets)

    scoped_df = active_df[active_df["url"].isin(urls_to_process)].copy()
    evaluated_urls: list[str] = []
    queued_repair_items = 0
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
        autotrader_median = None
        market_lifecycle = None
        at_matches = _score_autotrader_matches(autotrader_df, row, curve_key, limit=50)
        if not at_matches.empty and "price_value" in at_matches.columns:
            price_series = pd.to_numeric(at_matches["price_value"], errors="coerce").dropna()
            if not price_series.empty:
                autotrader_median = float(price_series.median())
        market_lifecycle = _market_lifecycle_summary(at_matches, base_estimate)
        queued_repair_items += _queue_unclassified_condition_fragments(row)
        run_curve_listing_analysis(
            row,
            base_estimate,
            comps_median=comps_median,
            comps_count=comps_count,
            analysis_context="active",
            autotrader_median=autotrader_median,
            carsales_estimate=base_estimate,
            listings_cluster_ok=bool(comps_count >= 3),
            market_lifecycle=market_lifecycle,
            force_refresh=force_refresh,
        )
        evaluated_urls.append(str(row.get("url")))
    return {
        "evaluated": len(evaluated_urls) + dropped_count,
        "urls": evaluated_urls,
        "dropped_coverage": dropped_count,
        "pruned_inactive": pruned_count,
        "queued_repair_items": queued_repair_items,
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


def diff_price_changed_listing_urls(before_df: pd.DataFrame, after_df: pd.DataFrame) -> set[str]:
    if after_df.empty or "url" not in after_df.columns:
        return set()
    after = after_df.copy()
    after["url"] = after["url"].astype(str).str.strip()
    if "price" not in after.columns:
        return set()

    after = after[["url", "price"]].drop_duplicates("url")
    if before_df.empty or "url" not in before_df.columns or "price" not in before_df.columns:
        return set(after["url"].dropna().astype(str).tolist())

    before = before_df.copy()
    before["url"] = before["url"].astype(str).str.strip()
    before = before[["url", "price"]].drop_duplicates("url")
    before_prices = {
        str(url).strip(): parse_currency(price)
        for url, price in before[["url", "price"]].itertuples(index=False, name=None)
        if str(url).strip()
    }

    changed_urls: set[str] = set()
    for url, price in after[["url", "price"]].itertuples(index=False, name=None):
        url_text = str(url).strip()
        if not url_text:
            continue
        before_price = before_prices.get(url_text)
        after_price = parse_currency(price)
        if before_price is None and after_price is None:
            continue
        if before_price is None or after_price is None or abs(float(after_price) - float(before_price)) > 0.01:
            changed_urls.add(url_text)
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


def load_ai_analysis_active_df() -> pd.DataFrame:
    active_df, _, _ = _prepare_active_scope()
    return active_df


def active_urls_from_frame(df: pd.DataFrame) -> list[str]:
    if df.empty or "url" not in df.columns:
        return []
    urls = df["url"].dropna().astype(str).tolist()
    return sorted({url for url in urls if url.startswith("http")})
