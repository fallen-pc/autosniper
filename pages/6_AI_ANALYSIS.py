from __future__ import annotations

import html
import json
import re
import time
import textwrap
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from scripts.ai_listing_valuation import run_curve_listing_analysis
from scripts.ai_price_analysis import _extract_hours_remaining
from shared.comps_engine import parse_currency, parse_numeric
from shared.canonical_tagging import UNCLASSIFIED, is_canonical_eligible
from shared.curves import load_curves, interpolate_base_by_year
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.grouping import extract_state
from shared.pipe_keys import looks_like_pipe_key, parse_pipe_key
from shared.repair_features import build_repair_features
from shared.spec import (
    get_spec_error,
    get_group_spec,
    is_series_allowed,
    load_spec,
    resolve_series_for_year,
    validate_curve_requirements,
)
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro
from shared.trim_multipliers import apply_trim_multiplier, load_trim_multipliers


st.set_page_config(page_title="AI Analysis (Curve)", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "AI ANALYSIS (CURVE)",
    "Curve-driven pricing cards using year + km anchors (comps shown for context).",
    show_logo=False,
)


required_files = [
    "active_vehicle_details_restricted.csv",
    "sold_cars_restricted.csv",
    "restricted_group_map.csv",
    "curves.csv",
]
missing = ensure_datasets_available(required_files)
if missing:
    st.error(
        "Missing required datasets: "
        + ", ".join(missing)
        + ". Run the restricted dataset build and ensure curves.csv exists."
    )
    st.stop()


COROLLA_GROUPS = {
    "toyota_corolla_hatch_petrol_auto_ascent_fwd_2013_2015",
    "toyota_corolla_hatch_petrol_auto_ascent_fwd_2016_2018",
    "toyota_corolla_hatch_petrol_auto_ascent_fwd_2019_2023",
    "toyota_corolla_sedan_petrol_auto_ascent_fwd_2013_2015",
    "toyota_corolla_sedan_petrol_auto_ascent_fwd_2016_2018",
    "toyota_corolla_sedan_petrol_auto_ascent_fwd_2019_2023",
}
SPORT_TRIM_PATTERN = re.compile(r"\b(sport|sports|sx|zr|zrx)\b|sportivo|levin", re.IGNORECASE)
ENGINE_DEFECT_PATTERN = re.compile(r"engine noise observed|engine idling rough", re.IGNORECASE)
AUTOTRADER_OUTPUT = Path("autotrader_isolated/output/first_page_results.csv")


def _format_currency(value: Optional[float]) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return f"${value:,.0f}"


def _safe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _safe_text(value: object, fallback: str = "N/A") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return fallback
    return text


def _format_count(value: object) -> str:
    count = _safe_int(value)
    return f"{count:,}" if count is not None else "N/A"


def _format_currency_value(value: Optional[float]) -> str:
    formatted = _format_currency(value)
    return formatted if formatted else "N/A"


def _format_price_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    if isinstance(value, (int, float)):
        return _format_currency_value(float(value))
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return "N/A"
    return text


def _format_odometer(value: object) -> str:
    odo_val = parse_numeric(value)
    if odo_val is None or (isinstance(odo_val, float) and pd.isna(odo_val)):
        return "N/A"
    return f"{int(round(odo_val)):,} km"


def _format_time_remaining(hours_remaining: Optional[float], fallback_text: object) -> str:
    if hours_remaining is not None and not pd.isna(hours_remaining):
        total_minutes = max(0, int(round(float(hours_remaining) * 60)))
        days = total_minutes // (24 * 60)
        hours = (total_minutes % (24 * 60)) // 60
        minutes = total_minutes % 60
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    fallback = _safe_text(fallback_text, fallback="N/A")
    if fallback == "N/A":
        return fallback
    lowered = fallback.lower()
    if any(keyword in lowered for keyword in ("ended", "sold", "closed")):
        return "Ended"
    if re.search(r"\d+\s*[dhms]", lowered):
        return fallback
    date_hint = (
        re.search(r"\d{4}-\d{2}-\d{2}", lowered)
        or re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", lowered)
        or re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b", lowered)
        or ":" in lowered
    )
    if date_hint:
        return "N/A"
    return fallback


def _extract_trim_text(row: pd.Series) -> str:
    for field in ("trim", "variant", "series", "model"):
        text = _safe_text(row.get(field), fallback="")
        if text and text != "N/A":
            return text
    return ""


def _parse_percent(value: object) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _format_percent(value: Optional[float]) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    return f"{value:.1f}%"


def _format_rego(expiry: object, rego_no: object) -> str:
    expiry_text = _safe_text(expiry, fallback="")
    rego_text = _safe_text(rego_no, fallback="")
    if expiry_text and expiry_text != "N/A":
        return expiry_text
    if rego_text and rego_text != "N/A":
        return rego_text
    return "Unregistered"


def _map_verdict_label(verdict: str) -> tuple[str, str]:
    verdict_lower = (verdict or "").lower()
    if "not eligible" in verdict_lower:
        return "Not eligible", "verdict-marginal"
    if "strong" in verdict_lower or "good" in verdict_lower:
        return "Good", "verdict-good"
    if "conditional" in verdict_lower or "marginal" in verdict_lower:
        return "Marginal", "verdict-marginal"
    if "avoid" in verdict_lower:
        return "Avoid", "verdict-avoid"
    if "trap" in verdict_lower:
        return "Avoid", "verdict-avoid"
    if "not covered" in verdict_lower:
        return "Marginal", "verdict-marginal"
    return "Marginal", "verdict-marginal"


def _parse_risk_flags(flags_text: object) -> list[str]:
    flags_raw = _safe_text(flags_text, fallback="")
    if not flags_raw:
        return []
    readable_map = {
        "HIGH_KM": "High km",
        "UNREGISTERED": "Unregistered",
        "NO_SERVICE_HISTORY": "No service history",
        "NO_MANUAL": "No papers",
        "MISSING_KEYS": "Missing keys",
        "ENGINE_UNKNOWN": "Engine unknown",
        "WARNING_LIGHT": "Warning light",
        "NO_EDGE": "No edge",
    }
    flags = []
    for raw_flag in flags_raw.split("|"):
        raw_flag = raw_flag.strip()
        if not raw_flag:
            continue
        flags.append(readable_map.get(raw_flag, raw_flag.replace("_", " ").title()))
    return flags


def _format_risk_flags(flags_text: object, max_flags: int = 3) -> str:
    flags = _parse_risk_flags(flags_text)
    if not flags:
        return "None"
    if len(flags) > max_flags:
        return f"{', '.join(flags[:max_flags])} +{len(flags) - max_flags}"
    return ", ".join(flags)


def _detect_condition_flags(condition_text: object) -> list[str]:
    if condition_text is None or (isinstance(condition_text, float) and pd.isna(condition_text)):
        return []
    text = str(condition_text).lower()
    if not text:
        return []
    keywords = [
        ("statutory", "Statutory write-off"),
        ("repairable", "Repairable write-off"),
        ("write-off", "Write-off"),
        ("wovr", "WOVR"),
        ("ppsr", "PPSR check"),
        ("encumbrance", "Encumbrance"),
        ("hail", "Hail damage"),
        ("flood", "Flood"),
        ("fire", "Fire damage"),
        ("burn", "Fire damage"),
        ("rust", "Rust"),
        ("smoke", "Smoke"),
        ("warning light", "Warning light"),
        ("engine light", "Engine light"),
        ("no start", "No start"),
        ("not running", "Not running"),
        ("does not run", "Not running"),
        ("damage", "Damage noted"),
    ]
    flags: list[str] = []
    for key, label in keywords:
        if key in text and label not in flags:
            flags.append(label)
    return flags


def _shorten_text(value: object, width: int = 72) -> str:
    text = _safe_text(value, fallback="")
    if not text:
        return "N/A"
    return textwrap.shorten(text, width=width, placeholder="...")


def _format_yes_no(value: object) -> str:
    text = _safe_text(value, fallback="")
    if not text:
        return "Unknown"
    lowered = text.lower()
    if lowered in {"yes", "y", "true", "present"}:
        return "Yes"
    if lowered in {"no", "n", "false", "missing", "none"}:
        return "No"
    return text


def _rego_status(expiry: object, rego_no: object) -> str:
    expiry_text = _safe_text(expiry, fallback="")
    rego_text = _safe_text(rego_no, fallback="")
    combined = f"{expiry_text} {rego_text}".lower()
    if "unregistered" in combined or "no plates" in combined:
        return "Unregistered"
    if not expiry_text and not rego_text:
        return "Unregistered"
    return "Registered"


def _round_to_10(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value / 10.0) * 10.0


def _yes_no_value(value: object) -> str:
    text = _safe_text(value, fallback="").lower()
    if text in {"yes", "y", "true", "present"}:
        return "yes"
    if text in {"no", "n", "false", "missing", "none", "absent", "not present", "not supplied"}:
        return "no"
    return ""


def _keys_pill(row: pd.Series) -> tuple[str, str]:
    key_value = _yes_no_value(row.get("key"))
    spare_value = _yes_no_value(row.get("spare_key"))
    if key_value == "no":
        return "Spare keys: No", "chip danger"
    if key_value == "yes":
        if spare_value == "yes":
            return "Spare keys: Yes", "chip good"
        if spare_value == "no":
            return "Spare keys: No", "chip warn"
    return "Spare keys: No", "chip warn"


def _manual_pill(value: object) -> tuple[str, str]:
    manual_value = _yes_no_value(value)
    if manual_value == "yes":
        return "Manual: Yes", "chip good"
    return "Manual: No", "chip warn"


def _service_pill(value: object) -> tuple[str, str]:
    text = _safe_text(value, fallback="").lower()
    if "partial" in text:
        return "Service: Partial", "chip warn"
    if text in {"yes", "full", "complete"} or "full" in text:
        return "Service: Full", "chip good"
    if text in {"no", "none"} or text == "no":
        return "Service: None", "chip danger"
    return "Service: Partial", "chip warn"


def _km_pill(odometer_value: object, year_value: object) -> tuple[str, str]:
    odometer_numeric = parse_numeric(odometer_value)
    year_int = _safe_int(year_value)
    if odometer_numeric is None or year_int is None:
        return "KM: N/A", "chip"
    if odometer_numeric >= 350000:
        km_display = f"{int(round(odometer_numeric)):,}"
        return f"KM: {km_display}", "chip danger"
    current_year = int(time.strftime("%Y"))
    age_years = max(1, current_year - year_int)
    expected_km = age_years * 15000
    ratio = odometer_numeric / expected_km if expected_km > 0 else None
    km_display = f"{int(round(odometer_numeric)):,}"
    if ratio is None:
        return f"KM: {km_display}", "chip"
    if ratio <= 1.05:
        return f"KM: {km_display}", "chip good"
    if ratio <= 1.35:
        return f"KM: {km_display}", "chip warn"
    return f"KM: {km_display}", "chip danger"


def _estimate_expected_sale(
    curve_estimate: Optional[float],
    comps_median: Optional[float],
    comps_count: Optional[int],
) -> tuple[Optional[float], str]:
    if curve_estimate is None:
        return None, "No curve estimate"
    return _round_to_10(curve_estimate), "Curve estimate (year + km)"


@st.cache_data(ttl=300)
def load_active_data() -> pd.DataFrame:
    active_path = dataset_path("active_vehicle_details_restricted.csv")
    df = pd.read_csv(active_path)
    df["url"] = df["url"].astype(str).str.strip()
    df["odometer_numeric"] = df["odometer_reading"].apply(parse_numeric)
    df["price_numeric"] = df["price"].apply(parse_currency) if "price" in df.columns else None
    return df


@st.cache_data(ttl=300)
def load_live_active_data() -> pd.DataFrame:
    live_path = dataset_path("active_vehicle_details.csv")
    if not live_path.exists():
        return pd.DataFrame()
    df = pd.read_csv(live_path)
    if "status" in df.columns:
        df["status"] = df["status"].astype(str).str.lower().str.strip()
        df = df[df["status"] == "active"].copy()
    df["url"] = df["url"].astype(str).str.strip()
    return df


@st.cache_data(ttl=300)
def load_group_map() -> pd.DataFrame:
    path = dataset_path("restricted_group_map.csv")
    df = pd.read_csv(path)
    df["url"] = df["url"].astype(str).str.strip()
    if "group_id" not in df.columns and "canonical_tag" in df.columns:
        df["group_id"] = df["canonical_tag"]
    return df


@st.cache_data(ttl=300)
def load_sold_data() -> pd.DataFrame:
    sold_path = dataset_path("sold_cars_restricted.csv")
    df = pd.read_csv(sold_path)
    df["url"] = df["url"].astype(str).str.strip()
    df["odometer_numeric"] = df["odometer_reading"].apply(parse_numeric)
    df["price_numeric"] = df["price"].apply(parse_currency)
    return df


def _select_sold_subset(
    sold_df: pd.DataFrame,
    group_id: object,
    year_val: Optional[int],
    min_year_samples: int = 3,
) -> pd.DataFrame:
    if sold_df.empty or not group_id:
        return pd.DataFrame()
    subset = sold_df[sold_df["group_id"] == group_id]
    if year_val is None or "year_int" not in subset.columns:
        return subset
    year_subset = subset[subset["year_int"] == year_val]
    if len(year_subset) >= min_year_samples:
        return year_subset
    return subset


def _km_percentile(series: pd.Series, target_km: Optional[float]) -> Optional[float]:
    if target_km is None or series is None or series.empty:
        return None
    values = series.dropna().astype(float)
    if values.empty:
        return None
    return float((values <= float(target_km)).sum() / len(values))


def _build_historical_matches(series: pd.Series, limit: int = 40) -> list[dict[str, float]]:
    if series is None:
        return []
    values = series.dropna().astype(float).tolist()
    if not values:
        return []
    trimmed = values[:limit]
    return [{"km": float(value), "spec_match": True} for value in trimmed]


def _normalize_match_text(value: object) -> str:
    text = _safe_text(value, fallback="")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _variant_score(listing_variant: str, candidate_variant: str) -> float:
    if not listing_variant or not candidate_variant:
        return 0.0
    listing_tokens = [token for token in listing_variant.split() if token]
    if not listing_tokens:
        return 0.0
    candidate_tokens = set(candidate_variant.split())
    if not candidate_tokens:
        return 0.0
    overlap = sum(1 for token in listing_tokens if token in candidate_tokens)
    return overlap / len(listing_tokens)


def _filter_autotrader_text(
    df: pd.DataFrame, column: str, needle: str
) -> pd.DataFrame:
    if not needle or column not in df.columns:
        return df
    exact = df[df[column] == needle]
    if not exact.empty:
        return exact
    return df[df[column].str.contains(rf"\\b{re.escape(needle)}\\b", na=False)]


@st.cache_data(ttl=300)
def load_autotrader_data() -> pd.DataFrame:
    if not AUTOTRADER_OUTPUT.exists():
        return pd.DataFrame()
    df = pd.read_csv(AUTOTRADER_OUTPUT)
    for col in (
        "year",
        "make",
        "model",
        "variant",
        "price",
        "odometer",
        "location",
        "transmission",
        "fuel_type",
        "rego",
        "url",
    ):
        if col not in df.columns:
            df[col] = ""
    df["make_norm"] = df["make"].apply(_normalize_match_text)
    df["model_norm"] = df["model"].apply(_normalize_match_text)
    df["variant_norm"] = df["variant"].apply(_normalize_match_text)
    df["transmission_norm"] = df["transmission"].apply(_normalize_match_text)
    df["fuel_norm"] = df["fuel_type"].apply(_normalize_match_text)
    df["year_int"] = df["year"].apply(_safe_int)
    df["price_value"] = df["price"].apply(parse_currency)
    df["odometer_value"] = df["odometer"].apply(parse_numeric)
    return df


def _find_autotrader_matches(
    df: pd.DataFrame,
    year: Optional[int],
    make: str,
    model: str,
    variant: str,
    transmission: str,
    fuel_type: str,
    limit: int = 6,
) -> pd.DataFrame:
    if df.empty:
        return df
    candidates = df.copy()
    make_norm = _normalize_match_text(make)
    model_norm = _normalize_match_text(model)
    variant_norm = _normalize_match_text(variant)
    candidates = _filter_autotrader_text(candidates, "make_norm", make_norm)
    candidates = _filter_autotrader_text(candidates, "model_norm", model_norm)
    if transmission:
        trans_norm = _normalize_match_text(transmission)
        trans_series = candidates["transmission_norm"].fillna("")
        if "manual" in trans_norm:
            candidates = candidates[
                trans_series.str.contains(r"\bmanual\b", na=True) | (trans_series == "")
            ]
        elif "auto" in trans_norm or "cvt" in trans_norm:
            candidates = candidates[
                trans_series.str.contains(r"\b(auto|automatic|cvt)\b", na=True) | (trans_series == "")
            ]
    if fuel_type:
        fuel_norm = _normalize_match_text(fuel_type)
        fuel_series = candidates["fuel_norm"].fillna("")
        if "diesel" in fuel_norm:
            candidates = candidates[
                fuel_series.str.contains(r"\bdiesel\b", na=True) | (fuel_series == "")
            ]
        elif "hybrid" in fuel_norm:
            candidates = candidates[
                fuel_series.str.contains(r"\bhybrid\b", na=True) | (fuel_series == "")
            ]
        elif "petrol" in fuel_norm or "unleaded" in fuel_norm:
            candidates = candidates[
                fuel_series.str.contains(r"\b(petrol|unleaded)\b", na=True) | (fuel_series == "")
            ]
    if year is not None and "year_int" in candidates.columns:
        if candidates["year_int"].notna().any():
            candidates = candidates[candidates["year_int"] == year]
    if candidates.empty:
        return candidates
    if variant_norm:
        candidates = candidates.copy()
        candidates["variant_score"] = candidates["variant_norm"].apply(
            lambda value: _variant_score(variant_norm, value)
        )
        scored = candidates[candidates["variant_score"] > 0].copy()
        if not scored.empty:
            candidates = scored
        sort_cols = ["variant_score"]
        ascending = [False]
        if "price_value" in candidates.columns:
            sort_cols.append("price_value")
            ascending.append(True)
        candidates = candidates.sort_values(by=sort_cols, ascending=ascending)
    elif "price_value" in candidates.columns:
        candidates = candidates.sort_values(by=["price_value"], ascending=[True])
    return candidates.head(limit)


def _exclude_corolla_sport_comps(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "group_id" not in df.columns:
        return df

    def _is_corolla_group(value: object) -> bool:
        parsed = parse_pipe_key(value)
        if parsed:
            model, group_key, _, _ = parsed
            return model == "corolla" and group_key in {"hatch_petrol_auto", "sedan_petrol_auto"}
        return value in COROLLA_GROUPS

    corolla_mask = df["group_id"].apply(_is_corolla_group)
    if not corolla_mask.any():
        return df
    text_fields = [field for field in ("variant", "model", "series", "trim") if field in df.columns]
    if not text_fields:
        return df
    text_series = (
        df.loc[corolla_mask, text_fields]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .str.lower()
    )
    sport_mask = text_series.str.contains(SPORT_TRIM_PATTERN, na=False)
    if not sport_mask.any():
        return df
    return df.drop(index=text_series[sport_mask].index)


def _exclude_major_engine_defects(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "general_condition" not in df.columns:
        return df

    def _has_major(text: object) -> bool:
        if text is None or (isinstance(text, float) and pd.isna(text)):
            return False
        if ENGINE_DEFECT_PATTERN.search(str(text)):
            return True
        features = build_repair_features(text)
        return "engine_mechanical" in features.tags or "non_operational" in features.tags

    mask = df["general_condition"].apply(_has_major)
    if not mask.any():
        return df
    return df.loc[~mask].copy()


curves_df = load_curves()
active_df = load_active_data()
live_df = load_live_active_data()
group_map_df = load_group_map()
sold_df = load_sold_data()
autotrader_df = load_autotrader_data()
spec = load_spec()
spec_error = get_spec_error(spec)
if spec_error == "pyyaml_missing":
    st.warning("Spec checks disabled: install `pyyaml` to enable config/spec_v1.yaml validation.")
    spec = {}

trim_config = load_trim_multipliers()
if trim_config.get("_error") == "pyyaml_missing":
    st.warning("Trim multipliers disabled: install `pyyaml` to enable config/trim_multipliers.yaml.")
    trim_config = {}

spec_issues = []
if spec and not curves_df.empty:
    sample_group = curves_df["group_id"].dropna().iloc[0] if "group_id" in curves_df.columns else None
    if not looks_like_pipe_key(sample_group):
        spec_issues = validate_curve_requirements(spec, curves_df)
if spec_issues:
    issue_preview = "\n".join(spec_issues[:10])
    extra = "" if len(spec_issues) <= 10 else f"\n...and {len(spec_issues) - 10} more"
    st.warning(f"Spec/curve issues detected:\n{issue_preview}{extra}")

active_groups = group_map_df[group_map_df["source"] == "active"][
    ["url", "group_id", "canonical_tag", "reason_code"]
].rename(columns={"reason_code": "canonical_reason"})
active_df = active_df.merge(active_groups, on="url", how="left")

if not live_df.empty:
    live_fields = ["url", "price", "bids", "time_remaining_or_date_sold", "location"]
    live_subset = live_df[[field for field in live_fields if field in live_df.columns]].copy()
    active_df = active_df.merge(live_subset, on="url", how="left", suffixes=("", "_live"))
    for field in ("price", "bids", "time_remaining_or_date_sold", "location"):
        live_field = f"{field}_live"
        if live_field in active_df.columns:
            active_df[field] = active_df[field].where(
                active_df[field].notna(),
                active_df[live_field],
            )
            active_df.drop(columns=[live_field], inplace=True)

if "time_remaining_or_date_sold" in active_df.columns:
    active_df["hours_remaining"] = active_df["time_remaining_or_date_sold"].apply(_extract_hours_remaining)
elif "date_sold" in active_df.columns:
    active_df["hours_remaining"] = active_df["date_sold"].apply(_extract_hours_remaining)
else:
    active_df["hours_remaining"] = None
if "price" in active_df.columns:
    active_df["price_numeric"] = active_df["price"].apply(parse_currency)

sold_groups = group_map_df[group_map_df["source"] == "sold"][
    ["url", "group_id", "canonical_tag", "reason_code"]
].rename(columns={"reason_code": "canonical_reason"})
sold_df = sold_df.merge(sold_groups, on="url", how="left")
sold_df = _exclude_corolla_sport_comps(sold_df)
sold_df = _exclude_major_engine_defects(sold_df)
sold_df["year_int"] = sold_df["year"].apply(_safe_int) if "year" in sold_df.columns else None

sold_stats_group = (
    sold_df.dropna(subset=["group_id", "price_numeric"])
    .groupby("group_id")["price_numeric"]
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
    sold_df.dropna(subset=["group_id", "price_numeric", "year_int"])
    .groupby(["group_id", "year_int"])["price_numeric"]
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


st.sidebar.header("Filters")
group_values = sorted({str(val).strip() for val in group_map_df["group_id"].dropna().tolist() if str(val).strip()})
group_filter = st.sidebar.selectbox("Group ID", ["All"] + group_values)
refresh_clicked = st.sidebar.button("Refresh curve valuations")
force_refresh = refresh_clicked

st.markdown(
    clean_html(
        """
        <style>
        #sticky-filter-anchor + div {
            position: sticky;
            top: 0.5rem;
            z-index: 40;
            background: rgba(11, 15, 20, 0.96);
            border: 1px solid rgba(31, 182, 255, 0.45);
            border-radius: 14px;
            padding: 0.85rem 1rem;
            margin-bottom: 1.2rem;
            box-shadow: 0 10px 26px rgba(0, 0, 0, 0.3);
            backdrop-filter: blur(6px);
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

st.markdown("<div id=\"sticky-filter-anchor\"></div>", unsafe_allow_html=True)
filter_cols = st.columns([1.1, 1, 1.2, 1], gap="medium")
with filter_cols[0]:
    sort_choice = st.selectbox(
        "Sort by",
        ["Profit %", "Max Bid", "Auction ending soon"],
        index=0,
    )
with filter_cols[1]:
    min_margin = st.slider("Min margin %", 0.0, 40.0, 0.0, 1.0)
with filter_cols[2]:
    time_bucket = st.radio(
        "Time bucket",
        ["All", "<24h", "1-2d", "2-3d", "3+d"],
        horizontal=True,
    )
with filter_cols[3]:
    hide_avoid = st.checkbox("Hide Avoid", value=True)
    hide_no_max_bid = st.checkbox("Hide N/A Max Bid", value=True)

TIME_BUCKETS: dict[str, tuple[Optional[float], Optional[float]]] = {
    "All": (None, None),
    "<24h": (0.0, 24.0),
    "1-2d": (24.0, 48.0),
    "2-3d": (48.0, 72.0),
    "3+d": (72.0, None),
}
min_hours, max_hours = TIME_BUCKETS.get(time_bucket, (None, None))

st.markdown(
    clean_html(
        """
        <style>
        :root {
            --sniper-card: #0b0f14;
            --sniper-card-deep: #070b10;
            --sniper-cyan: #27b6ff;
            --sniper-cyan-soft: rgba(39, 182, 255, 0.2);
            --sniper-green: #2cff9a;
            --sniper-amber: #ffb347;
            --sniper-red: #ff4d4d;
        }
        .vehicle-card {
            --card-glow: 0 0 0 rgba(0, 0, 0, 0);
            --card-hover: 0 0 0 rgba(0, 0, 0, 0);
            background: linear-gradient(180deg, #08121d 0%, #0b0f14 30%, #0b0f14 100%);
            border: 1px solid rgba(39, 182, 255, 0.35);
            border-top: 3px solid var(--sniper-cyan);
            border-radius: 14px;
            padding: 0.5rem 0.75rem 0.45rem;
            margin-bottom: 0.55rem;
            box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.25), var(--card-glow), var(--card-hover);
            transition: box-shadow 0.15s ease, transform 0.15s ease;
        }
        .vehicle-card:hover {
            --card-hover: 0 0 12px rgba(39, 182, 255, 0.18);
            transform: translateY(-1px);
        }
        .vehicle-card.profit-tier-high {
            --card-glow: 0 0 14px rgba(44, 255, 154, 0.32);
        }
        .vehicle-card.profit-tier-mid {
            --card-glow: 0 0 0 rgba(0, 0, 0, 0);
        }
        .card-top {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 0.6rem;
            padding-bottom: 0.3rem;
            border-bottom: 1px solid rgba(39, 182, 255, 0.16);
        }
        .vehicle-title-block {
            display: flex;
            flex-direction: column;
            gap: 0.1rem;
            min-width: 220px;
        }
        .vehicle-title {
            display: flex;
            align-items: baseline;
            gap: 0.4rem;
            font-size: 1.24rem;
            font-weight: 800;
            line-height: 1;
            color: var(--autosniper-primary);
        }
        .vehicle-title-text {
            flex: 1 1 auto;
            min-width: 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .vehicle-location {
            flex: 0 0 auto;
            font-size: 0.72rem;
            font-weight: 600;
            color: rgba(255, 255, 255, 0.6);
        }
        .vehicle-variant {
            font-size: 0.75rem;
            color: var(--autosniper-muted);
        }
        .card-top-meta {
            font-size: 0.56rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: rgba(255, 255, 255, 0.45);
        }
        .card-top-right {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .card-actions a {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            border: 1px solid rgba(39, 182, 255, 0.6);
            color: var(--autosniper-primary);
            text-decoration: none;
            font-size: 0.62rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
        }
        .card-actions a:hover {
            background: rgba(39, 182, 255, 0.12);
        }
        .card-metrics {
            margin-top: 0.35rem;
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.35rem;
            align-items: stretch;
        }
        .metric-box {
            background: rgba(8, 12, 18, 0.65);
            border: 1px solid rgba(39, 182, 255, 0.3);
            border-radius: 9px;
            padding: 0.3rem 0.4rem;
            min-height: 40px;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .metric-label {
            font-size: 0.52rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: var(--autosniper-muted);
            margin-bottom: 0.08rem;
        }
        .metric-value {
            font-size: 1.28rem;
            font-weight: 800;
            color: var(--autosniper-primary);
            line-height: 0.95;
        }
        .metric-box.primary .metric-value {
            font-size: 1.28rem;
        }
        .metric-sub {
            font-size: 0.62rem;
            color: rgba(255, 255, 255, 0.6);
            margin-top: 0.2rem;
        }
        .verdict-pill {
            border-radius: 999px;
            padding: 0.3rem 0.65rem;
            font-size: 0.64rem;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            font-weight: 800;
            text-align: center;
            border: 1px solid;
        }
        .verdict-good-pill {
            background: rgba(44, 255, 154, 0.12);
            border-color: rgba(44, 255, 154, 0.85);
            color: #e9fff5;
            box-shadow: 0 0 12px rgba(44, 255, 154, 0.35);
        }
        .verdict-marginal-pill {
            background: rgba(255, 179, 71, 0.14);
            border-color: rgba(255, 179, 71, 0.8);
            color: #fff3e0;
            box-shadow: 0 0 12px rgba(255, 179, 71, 0.3);
        }
        .verdict-avoid-pill {
            background: rgba(255, 77, 77, 0.14);
            border-color: rgba(255, 77, 77, 0.85);
            color: #ffe9e9;
            box-shadow: 0 0 12px rgba(255, 77, 77, 0.32);
        }
        .top-buy-pill {
            background: rgba(57, 255, 152, 0.18);
            border-color: rgba(57, 255, 152, 0.9);
            color: #ecfff5;
            box-shadow: 0 0 14px rgba(57, 255, 152, 0.45);
        }
        .chip-row {
            margin-top: 0.3rem;
            display: flex;
            flex-wrap: wrap;
            gap: 0.3rem;
        }
        .chip {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.16rem 0.45rem;
            border-radius: 999px;
            border: 1px solid rgba(39, 182, 255, 0.35);
            background: rgba(11, 15, 20, 0.6);
            font-size: 0.6rem;
            color: rgba(255, 255, 255, 0.78);
        }
        .chip strong {
            color: rgba(255, 255, 255, 0.95);
            font-weight: 700;
        }
        .chip.danger {
            border-color: rgba(255, 77, 77, 0.6);
            background: rgba(255, 77, 77, 0.08);
        }
        .chip.warn {
            border-color: rgba(255, 179, 71, 0.7);
            background: rgba(255, 179, 71, 0.08);
        }
        .chip.good {
            border-color: rgba(44, 255, 154, 0.65);
            background: rgba(44, 255, 154, 0.08);
        }
        .details-section {
            margin-top: 0.6rem;
        }
        .details-section h4 {
            margin-bottom: 0.35rem;
            font-size: 0.95rem;
            color: var(--autosniper-primary);
        }
        div[data-testid="stExpander"] {
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            background: rgba(7, 10, 15, 0.45);
            box-shadow: none;
        }
        div[data-testid="stExpander"] summary {
            padding: 0.25rem 0.6rem;
            font-size: 0.72rem;
            color: rgba(255, 255, 255, 0.62);
        }
        div[data-testid="stExpander"] summary svg {
            transform: scale(0.85);
        }
        div[data-testid="stExpander"] .streamlit-expanderContent {
            padding: 0.45rem 0.7rem 0.7rem;
            font-size: 0.8rem;
        }
        div[data-testid="stExpander"] .stMarkdown p,
        div[data-testid="stExpander"] .stMarkdown li,
        div[data-testid="stExpander"] .stMarkdown span {
            font-size: 0.8rem;
            color: rgba(255, 255, 255, 0.75);
        }
        div[data-testid="stExpander"] ul {
            margin-top: 0.25rem;
            margin-bottom: 0.4rem;
        }
        div[data-testid="stExpander"] div[data-testid="stDataFrame"] {
            border: none;
        }
        div[data-testid="stExpander"] div[data-testid="stDataFrame"] table,
        div[data-testid="stExpander"] div[data-testid="stDataFrame"] th,
        div[data-testid="stExpander"] div[data-testid="stDataFrame"] td {
            border: none !important;
        }
        div[data-testid="stExpander"] div[data-testid="stDataFrame"] tbody tr:nth-child(even) {
            background: rgba(255, 255, 255, 0.03);
        }
        @media (max-width: 900px) {
            .card-top {
                flex-direction: column;
                align-items: flex-start;
            }
            .vehicle-title {
                white-space: normal;
            }
            .card-metrics {
                grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            }
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

filtered = active_df.copy()
if "hours_remaining" in filtered.columns and (min_hours is not None or max_hours is not None):
    filtered = filtered[filtered["hours_remaining"].notna()]
    if min_hours is not None:
        filtered = filtered[filtered["hours_remaining"] >= min_hours]
    if max_hours is not None:
        filtered = filtered[filtered["hours_remaining"] < max_hours]

if group_filter != "All":
    filtered = filtered[filtered["group_id"] == group_filter]

filtered = filtered.dropna(subset=["group_id"]).copy()

if filtered.empty:
    st.info("No active listings match the current filters.")
    st.stop()


results: list[Dict[str, Any]] = []
for _, row in filtered.iterrows():
    group_id = row.get("group_id")
    canonical_tag = row.get("canonical_tag")
    canonical_reason = _safe_text(row.get("canonical_reason"), fallback="").strip()
    year_val = _safe_int(row.get("year"))
    odo_val = row.get("odometer_numeric")
    spec_reason = ""
    series_key = None
    if not is_canonical_eligible(canonical_tag, canonical_reason):
        spec_reason = canonical_reason or "NOT_ELIGIBLE"
        results.append(
            {
                "url": row.get("url"),
                "curve_base": None,
                "curve_adjusted": None,
                "trim_multiplier": None,
                "computed_verdict": "Not Eligible",
                "recommended_max_bid": None,
                "resale_mid": None,
                "net_profit_worst": None,
                "spec_reason": spec_reason,
                "spec_series": None,
                "comps_count": 0,
                "comps_median": None,
                "comps_mean": None,
                "comps_min": None,
                "comps_max": None,
                "expected_sale": None,
                "expected_sale_note": "No curve / Not eligible",
            }
        )
        continue
    parsed = parse_pipe_key(group_id)
    if parsed:
        _, _, series_key, _ = parsed
    else:
        lookup_id = canonical_tag or group_id
        spec_group = get_group_spec(spec, lookup_id) if spec else None
        if spec and not spec_group:
            spec_reason = "UNKNOWN_GROUP_MAPPING"
        elif spec_group:
            series_key, spec_reason = resolve_series_for_year(spec, lookup_id, year_val)
            if not spec_reason and series_key and not is_series_allowed(spec_group, series_key):
                spec_reason = "SERIES_NOT_COVERED"

    curve_subset = curves_df
    if group_id:
        curve_subset = curve_subset[curve_subset["group_id"] == group_id]
    if curve_subset.empty and not spec_reason:
        spec_reason = "NO_CURVE"
    if series_key and not curve_subset.empty:
        curve_subset = curve_subset[curve_subset["series"] == series_key]
        if curve_subset.empty and not spec_reason:
            spec_reason = "SERIES_NOT_COVERED"

    base_estimate = None
    if not spec_reason:
        base_estimate = interpolate_base_by_year(curve_subset, group_id, year_val, odo_val)
    trim_multiplier = None
    adjusted_estimate = base_estimate
    if base_estimate is not None:
        trim_text = _extract_trim_text(row)
        adjusted_estimate, trim_multiplier = apply_trim_multiplier(
            base_estimate,
            group_id,
            trim_text,
            odo_val,
            trim_config,
        )
    stats = None
    if year_val is not None and (group_id, year_val) in sold_stats_year.index:
        stats = sold_stats_year.loc[(group_id, year_val)]
    elif group_id in sold_stats_group.index:
        stats = sold_stats_group.loc[group_id]
    comps_count = int(stats["comps_count"]) if stats is not None else 0
    comps_median = float(stats["comps_median"]) if stats is not None else None
    comps_mean = float(stats["comps_mean"]) if stats is not None else None
    comps_min = float(stats["comps_min"]) if stats is not None else None
    comps_max = float(stats["comps_max"]) if stats is not None else None
    expected_sale, expected_sale_note = _estimate_expected_sale(
        adjusted_estimate,
        comps_median,
        comps_count,
    )

    sold_subset = _select_sold_subset(sold_df, group_id, year_val)
    km_percentile = None
    historical_matches = []
    if not sold_subset.empty:
        km_percentile = _km_percentile(sold_subset["odometer_numeric"], odo_val)
        historical_matches = _build_historical_matches(sold_subset["odometer_numeric"])

    autotrader_median = None
    listings_cluster_ok = False
    if not autotrader_df.empty:
        listing_year = year_val
        listing_make = _safe_text(row.get("make"), fallback="")
        listing_model = _safe_text(row.get("model"), fallback="")
        listing_variant = _extract_trim_text(row)
        listing_transmission = _safe_text(row.get("transmission"), fallback="")
        listing_fuel = _safe_text(row.get("fuel_type"), fallback="")
        at_matches = _find_autotrader_matches(
            autotrader_df,
            listing_year,
            listing_make,
            listing_model,
            listing_variant,
            listing_transmission,
            listing_fuel,
        )
        if not at_matches.empty and "price_value" in at_matches.columns:
            price_series = at_matches["price_value"].dropna()
            if not price_series.empty:
                autotrader_median = float(price_series.median())
        listings_cluster_ok = len(at_matches) >= 3

    if adjusted_estimate is None:
        if not spec_reason:
            spec_reason = "NO_CURVE"
        results.append(
            {
                "url": row.get("url"),
                "curve_base": None,
                "curve_adjusted": None,
                "trim_multiplier": trim_multiplier,
                "computed_verdict": "Not Eligible",
                "recommended_max_bid": None,
                "resale_mid": None,
                "net_profit_worst": None,
                "spec_reason": spec_reason or "NOT_ELIGIBLE",
                "spec_series": series_key,
                "comps_count": comps_count,
                "comps_median": comps_median,
                "comps_mean": comps_mean,
                "comps_min": comps_min,
                "comps_max": comps_max,
                "expected_sale": expected_sale,
                "expected_sale_note": expected_sale_note or "No curve / Not eligible",
            }
        )
        continue

    analysis = run_curve_listing_analysis(
        row,
        adjusted_estimate,
        comps_median=comps_median,
        comps_count=comps_count,
        analysis_context="active",
        km_percentile=km_percentile,
        historical_matches=historical_matches,
        autotrader_median=autotrader_median,
        carsales_estimate=adjusted_estimate,
        listings_cluster_ok=listings_cluster_ok,
        force_refresh=force_refresh,
    )
    analysis["curve_base"] = base_estimate
    analysis["curve_adjusted"] = adjusted_estimate
    analysis["trim_multiplier"] = trim_multiplier
    analysis["comps_count"] = comps_count
    analysis["comps_median"] = comps_median
    analysis["comps_mean"] = comps_mean
    analysis["comps_min"] = comps_min
    analysis["comps_max"] = comps_max
    analysis["expected_sale"] = expected_sale
    analysis["expected_sale_note"] = expected_sale_note
    analysis["spec_reason"] = spec_reason or ""
    analysis["spec_series"] = series_key
    results.append(analysis)


results_df = pd.DataFrame(results)
output = filtered.merge(results_df, on="url", how="left")

def _compute_profit_margin_value(row: pd.Series) -> Optional[float]:
    margin_value = _parse_percent(row.get("profit_margin_percent"))
    if margin_value is not None:
        return margin_value
    net_profit = parse_currency(row.get("net_profit_worst")) or parse_currency(row.get("net_profit_mid"))
    resale = (
        parse_currency(row.get("resale_mid"))
        or parse_currency(row.get("expected_sale"))
        or parse_currency(row.get("curve_adjusted"))
    )
    if net_profit is not None and resale:
        return (net_profit / resale) * 100
    return None


def _compute_resale_value(row: pd.Series) -> Optional[float]:
    return (
        parse_currency(row.get("expected_sale"))
        or parse_currency(row.get("resale_mid"))
        or parse_currency(row.get("curve_adjusted"))
    )


def _compute_max_bid_value(row: pd.Series) -> Optional[float]:
    return parse_currency(row.get("recommended_max_bid")) or parse_currency(row.get("price"))


def _split_notes(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    return [note.strip() for note in text.split(";") if note.strip()]


def _parse_reason_list(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    return [item.strip() for item in text.split(";") if item.strip()]


def _truthy(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1"}:
        return True
    return False


output = output.copy()
output["profit_margin_value"] = output.apply(_compute_profit_margin_value, axis=1)
output["resale_value"] = output.apply(_compute_resale_value, axis=1)
output["max_bid_value"] = output.apply(_compute_max_bid_value, axis=1)
output["verdict_label"] = output["computed_verdict"].apply(lambda value: _map_verdict_label(str(value))[0])
output["verdict_class"] = output["computed_verdict"].apply(lambda value: _map_verdict_label(str(value))[1])

filtered_output = output.copy()
if group_filter != "All":
    filtered_output = filtered_output[filtered_output["group_id"] == group_filter]

if hide_avoid:
    filtered_output = filtered_output[filtered_output["verdict_label"] != "Avoid"]

if min_margin > 0:
    filtered_output = filtered_output[
        filtered_output["profit_margin_value"].fillna(-1) >= min_margin
    ]

if hide_no_max_bid:
    filtered_output = filtered_output[filtered_output["max_bid_value"].notna()]

if filtered_output.empty:
    st.info("No active listings match the current filters.")
    st.stop()

if sort_choice == "Profit %":
    filtered_output = filtered_output.sort_values(
        by=["profit_margin_value", "max_bid_value"],
        ascending=[False, False],
        na_position="last",
    )
elif sort_choice == "Max Bid":
    filtered_output = filtered_output.sort_values(
        by=["max_bid_value", "profit_margin_value"],
        ascending=[False, False],
        na_position="last",
    )
else:
    filtered_output = filtered_output.sort_values(
        by=["hours_remaining", "profit_margin_value"],
        ascending=[True, False],
        na_position="last",
    )

summary_html = clean_html(
    f"""
    <div class="autosniper-section">
        <div class="section-title">Restricted Listings</div>
        <div class="section-subtitle">
            Showing {len(filtered_output):,} of {len(output):,} listings in view.
        </div>
    </div>
    """
)
st.markdown(summary_html, unsafe_allow_html=True)


def _build_metric_box(label: str, value: str) -> str:
    return _build_metric_box_with_sub(label, value, None)


def _build_metric_box_with_sub(
    label: str, value: str, subtext: Optional[str], class_name: Optional[str] = None
) -> str:
    sub_html = f'<div class="metric-sub">{html.escape(subtext)}</div>' if subtext else ""
    class_attr = f"metric-box {class_name}".strip() if class_name else "metric-box"
    return "".join(
        [
            f'<div class="{class_attr}">',
            f'<div class="metric-label">{html.escape(label)}</div>',
            f'<div class="metric-value">{html.escape(value)}</div>',
            sub_html,
            "</div>",
        ]
    )


def _render_bullets(title: str, items: list[str]) -> None:
    cleaned = [item for item in items if item]
    if not cleaned:
        return
    st.markdown(f"**{title}**")
    st.markdown("\n".join(f"- {item}" for item in cleaned))


def _profit_tier_class(value: Optional[float]) -> str:
    if value is None or pd.isna(value):
        return "profit-tier-low"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "profit-tier-low"
    if numeric >= 25:
        return "profit-tier-high"
    if numeric >= 10:
        return "profit-tier-mid"
    return "profit-tier-low"


def render_listing_card(row: pd.Series) -> None:
    raw_title_parts = [
        _safe_text(row.get("year"), fallback=""),
        _safe_text(row.get("make"), fallback=""),
        _safe_text(row.get("model"), fallback=""),
        _safe_text(row.get("variant"), fallback=""),
    ]
    title_parts = [part for part in raw_title_parts if part and part != "N/A"]
    title = " ".join(title_parts)
    title = title or "Listing"
    title_html = html.escape(title)

    verdict_label = _safe_text(row.get("verdict_label"), fallback="Marginal")
    verdict_class = _safe_text(row.get("verdict_class"), fallback="verdict-marginal")
    verdict_pill_class = f"{verdict_class}-pill"
    profit_class = _profit_tier_class(row.get("profit_margin_value"))
    top_buy_badge = _safe_text(row.get("top_buy_badge"), fallback="").strip()
    if _truthy(row.get("is_top_buy")) and not top_buy_badge:
        top_buy_badge = "TOP BUY"
    top_buy_html = (
        f'<div class="verdict-pill top-buy-pill">{html.escape(top_buy_badge)}</div>'
        if top_buy_badge and top_buy_badge != "N/A"
        else ""
    )

    max_bid_display = _format_currency_value(row.get("max_bid_value"))
    resale_display = _format_currency_value(row.get("resale_value"))
    profit_pct_display = _format_percent(row.get("profit_margin_value"))

    current_price_display = _format_price_text(row.get("price"))
    raw_time_value = row.get("time_remaining_or_date_sold") or row.get("date_sold")
    time_left_display = _format_time_remaining(row.get("hours_remaining"), raw_time_value)

    rego_text = _format_rego(row.get("rego_expiry"), row.get("rego_no"))
    rego_status = _rego_status(row.get("rego_expiry"), row.get("rego_no"))
    location_state = extract_state(
        row.get("location_state") or row.get("rego_state") or row.get("location")
    )
    risk_flags = _parse_risk_flags(row.get("risk_flags"))
    condition_flags = _detect_condition_flags(row.get("general_condition"))
    combined_flags = []
    for flag in risk_flags + condition_flags:
        if flag and flag not in combined_flags:
            combined_flags.append(flag)
    risk_summary = "None"
    if combined_flags:
        risk_summary = (
            ", ".join(combined_flags[:3])
            if len(combined_flags) <= 3
            else f"{', '.join(combined_flags[:3])} +{len(combined_flags) - 3}"
        )
    canonical_reason = _safe_text(row.get("canonical_reason"), fallback="").strip()
    canonical_tag = _safe_text(row.get("canonical_tag"), fallback="").strip().lower()
    is_toyota = _safe_text(row.get("make"), fallback="").strip().lower() == "toyota" or canonical_tag.startswith(
        "toyota_"
    )
    drivetrain_warning = (
        canonical_reason == "[AMBIG_DRIVETRAIN]" and is_toyota
    )

    group_id = _safe_text(row.get("group_id"), fallback="")
    header_meta_parts = []
    if group_id and group_id != "N/A":
        header_meta_parts.append(f"Group {group_id}")
    header_meta = " | ".join(header_meta_parts)

    risk_chip_class = "chip"
    if combined_flags:
        risk_chip_class = "chip warn"

    rego_chip_class = "chip good" if rego_status == "Registered" else "chip danger"
    keys_label, keys_chip_class = _keys_pill(row)
    manual_label, manual_chip_class = _manual_pill(row.get("owners_manual"))
    service_label, service_chip_class = _service_pill(row.get("service_history"))
    odometer_value = row.get("odometer_numeric")
    if odometer_value is None or (isinstance(odometer_value, float) and pd.isna(odometer_value)):
        odometer_value = row.get("odometer_reading")
    km_label, km_chip_class = _km_pill(odometer_value, row.get("year"))
    location_badge = f"({location_state})" if location_state else ""

    card_html = "".join(
        [
            f'<div class="vehicle-card {verdict_class} {profit_class}">',
            '<div class="card-top">',
            '<div class="vehicle-title-block">',
            '<div class="vehicle-title">',
            f'<span class="vehicle-title-text">{title_html}</span>',
            f'<span class="vehicle-location">{html.escape(location_badge)}</span>' if location_badge else "",
            "</div>",
            f'<div class="card-top-meta">{html.escape(header_meta)}</div>' if header_meta else "",
            "</div>",
            '<div class="card-top-right">',
            f'<div class="verdict-pill {verdict_pill_class}">{html.escape(verdict_label)}</div>',
            top_buy_html,
            '<div class="card-actions">',
            f'<a href="{html.escape(_safe_text(row.get("url"), fallback=""))}" target="_blank">Open</a>'
            if _safe_text(row.get("url"), fallback="") != "N/A"
            else "",
            "</div>",
            "</div>",
            "</div>",
            '<div class="card-metrics">',
            _build_metric_box("Current price", current_price_display),
            _build_metric_box("Time left", time_left_display),
            _build_metric_box("Max bid", max_bid_display),
            _build_metric_box("Expected resale", resale_display),
            _build_metric_box("Profit %", profit_pct_display),
            "</div>",
            '<div class="chip-row">',
            f'<span class="{km_chip_class}">{html.escape(km_label)}</span>',
            f'<span class="{rego_chip_class}">Rego: {html.escape(rego_text)}</span>',
            f'<span class="{keys_chip_class}">{html.escape(keys_label)}</span>',
            f'<span class="{manual_chip_class}">{html.escape(manual_label)}</span>',
            f'<span class="{service_chip_class}">{html.escape(service_label)}</span>',
            f'<span class="{risk_chip_class}">Risk: {html.escape(risk_summary)}</span>',
            f'<span class="chip warn">AMBIG_DRIVETRAIN</span>' if drivetrain_warning else "",
            "</div>",
            "</div>",
        ]
    )
    st.markdown(card_html, unsafe_allow_html=True)

    with st.expander("Details", expanded=False):
        confidence_value = row.get("confidence")
        confidence_percent = None
        if confidence_value is not None and not (isinstance(confidence_value, float) and pd.isna(confidence_value)):
            try:
                confidence_percent = float(confidence_value) * 100
            except (TypeError, ValueError):
                confidence_percent = None
        confidence_text = _format_percent(confidence_percent)
        if confidence_text == "N/A":
            confidence_text = _format_percent(_parse_percent(row.get("profit_margin_percent")))

        ai_notes = _split_notes(row.get("confidence_notes"))
        expected_note = _safe_text(row.get("expected_sale_note"), fallback="")
        if expected_note:
            ai_notes.append(expected_note)
        if not ai_notes:
            ai_notes = [
                f"Confidence: {confidence_text}",
                f"Margin target: {profit_pct_display}",
            ]

        comps_min = _format_currency_value(row.get("comps_min"))
        comps_max = _format_currency_value(row.get("comps_max"))
        comps_range = (
            f"{comps_min} - {comps_max}"
            if comps_min != "N/A" or comps_max != "N/A"
            else "N/A"
        )
        comps_items = [
            f"Comps count: {_format_count(row.get('comps_count'))}",
            f"Median: {_format_currency_value(row.get('comps_median'))}",
            f"Range: {comps_range}",
            f"Expected sale: {resale_display}",
        ]

        calc_items = [
            f"Fees: {_format_price_text(row.get('fees_estimate'))}",
            f"Transport: {_format_price_text(row.get('transport_estimate'))}",
            f"Rego: {_format_price_text(row.get('rego_estimate'))}",
            f"Prep: {_format_price_text(row.get('prep_estimate'))}",
            f"Net profit (mid): {_format_price_text(row.get('net_profit_mid'))}",
            f"Net profit (worst): {_format_price_text(row.get('net_profit_worst'))}",
        ]

        risk_items = []
        if combined_flags:
            risk_items.append(f"Flags: {', '.join(combined_flags[:6])}")
        edge_note = _safe_text(row.get("edge_note"), fallback="")
        if edge_note:
            risk_items.append(edge_note)
        spec_reason = _safe_text(row.get("spec_reason"), fallback="")
        if spec_reason:
            risk_items.append(f"Spec coverage: {spec_reason}")
        condition_notes = _safe_text(row.get("general_condition"), fallback="")
        if condition_notes:
            risk_items.append(f"Condition: {condition_notes}")

        top_buy_failed = _parse_reason_list(row.get("top_buy_failed_reasons"))
        top_buy_passed = _parse_reason_list(row.get("top_buy_passed_reasons"))

        _render_bullets("AI reasoning", ai_notes[:4])
        _render_bullets("Comparable sales", comps_items)
        _render_bullets("Calculation breakdown", calc_items[:6])
        if top_buy_passed:
            _render_bullets("Top Buy passes", top_buy_passed[:6])
        if top_buy_failed:
            _render_bullets("Top Buy blockers", top_buy_failed[:6])
        _render_bullets("Notes / risks", risk_items[:4])

        group_id_value = row.get("group_id")
        if group_id_value and not (isinstance(group_id_value, float) and pd.isna(group_id_value)):
            comps_df = sold_df[sold_df["group_id"] == group_id_value].copy()
            listing_year = _safe_int(row.get("year"))
            if listing_year is not None and "year_int" in comps_df.columns:
                comps_df = comps_df[comps_df["year_int"] == listing_year]
            if not comps_df.empty:
                comps_df["date_sold_parsed"] = pd.to_datetime(
                    comps_df["date_sold"], errors="coerce"
                )
                comps_df = comps_df.sort_values(
                    by=["date_sold_parsed"], ascending=False, na_position="last"
                )
                comps_df = comps_df.head(6)
                display_cols = [
                    "year",
                    "make",
                    "model",
                    "variant",
                    "odometer_reading",
                    "price",
                    "date_sold",
                ]
                table_df = comps_df[[col for col in display_cols if col in comps_df.columns]].copy()
                if "url" in comps_df.columns:
                    table_df["listing"] = comps_df["url"]
                    ordered_cols = [col for col in display_cols if col in table_df.columns] + ["listing"]
                    table_df = table_df[ordered_cols]
                if "price" in table_df.columns:
                    table_df["price"] = table_df["price"].apply(_format_price_text)
                if "odometer_reading" in table_df.columns:
                    table_df["odometer_reading"] = table_df["odometer_reading"].apply(_format_odometer)
                st.markdown("**Top comps (latest)**")
                column_config = {}
                if "listing" in table_df.columns:
                    column_config["listing"] = st.column_config.LinkColumn(
                        "Listing",
                        display_text="Open",
                    )
                st.dataframe(
                    table_df,
                    width="stretch",
                    hide_index=True,
                    column_config=column_config,
                )

        st.markdown("**Autotrader comparison**")
        if autotrader_df.empty:
            st.caption(
                f"No Autotrader CSV found at {AUTOTRADER_OUTPUT}. "
                "Run the Autotrader scraper to generate it."
            )
        else:
            listing_year = _safe_int(row.get("year"))
            listing_make = _safe_text(row.get("make"), fallback="")
            listing_model = _safe_text(row.get("model"), fallback="")
            listing_variant = _extract_trim_text(row)
            listing_transmission = _safe_text(row.get("transmission"), fallback="")
            listing_fuel = _safe_text(row.get("fuel_type"), fallback="")
            matches = _find_autotrader_matches(
                autotrader_df,
                listing_year,
                listing_make,
                listing_model,
                listing_variant,
                listing_transmission,
                listing_fuel,
            )
            if matches.empty:
                st.caption("No matches found in the current Autotrader snapshot.")
            else:
                st.caption(f"Matches: {len(matches)}")
                display_cols = [
                    "year",
                    "make",
                    "model",
                    "variant",
                    "price",
                    "odometer",
                    "location",
                    "transmission",
                    "fuel_type",
                    "rego",
                ]
                table_df = matches[[col for col in display_cols if col in matches.columns]].copy()
                if "price" in table_df.columns:
                    table_df["price"] = table_df["price"].apply(_format_price_text)
                if "odometer" in table_df.columns:
                    table_df["odometer"] = table_df["odometer"].apply(_format_odometer)
                column_config = {}
                if "url" in matches.columns:
                    table_df["listing"] = matches["url"]
                    ordered_cols = [col for col in display_cols if col in table_df.columns]
                    if "listing" not in ordered_cols:
                        ordered_cols.append("listing")
                    table_df = table_df[ordered_cols]
                    column_config["listing"] = st.column_config.LinkColumn(
                        "Listing",
                        display_text="Open",
                    )
                st.dataframe(
                    table_df,
                    width="stretch",
                    hide_index=True,
                    column_config=column_config,
                )

        listing_url = _safe_text(row.get("url"), fallback="")
        if listing_url:
            st.markdown(f"[Open listing]({listing_url})")


for _, row in filtered_output.iterrows():
    render_listing_card(row)

st.caption(f"Last refreshed: {time.strftime('%Y-%m-%d %H:%M:%S')}")
