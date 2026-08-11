from __future__ import annotations

import html
import json
import math
import re
import time
import textwrap
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st
from ops.active_monitor import (
    _exclude_shortlist_ineligible_rows,
    _load_external_auction_active_rows,
)
from shared.navigation import render_sidebar_navigation

from scripts.ai_listing_valuation import MIN_NET_PROFIT_ABSOLUTE, load_cached_results, run_curve_listing_analysis
from scripts.ai_price_analysis import _extract_hours_remaining
from shared.comps_engine import parse_currency, parse_numeric
from shared.canonical_tagging import UNCLASSIFIED, is_canonical_eligible, tag_dataframe
from shared.curves import (
    get_curve_points,
    interpolate_base_by_year,
    interpolate_price_by_km,
    km_within_curve_coverage,
    list_curve_tags,
    load_curves,
    resolve_curve_canonical_tag,
)
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.decision_policy import action_display_parts, derive_action_label_from_row
from shared.global_filters import apply_global_sidebar_filters, render_global_sidebar_filters
from shared.buying_lanes import (
    ALL_CAPITAL_LANES,
    CAPITAL_LANE_OPTIONS,
    HIGHER_CAPITAL_LANE,
    classify_capital_lane,
    filter_capital_lane,
)
from shared.location_utils import extract_state
from shared.repair_features import build_repair_features
from shared.repair_pricing import (
    PANEL_CAP,
    PANEL_RATE,
    WINDSCREEN_ADAS,
    WINDSCREEN_STD,
    assess_repairs,
    repair_fragments_to_records,
    vehicle_class_for_listing,
)
from shared.repair_review import (
    append_live_review_items,
    append_unclassified_condition_lines,
    repair_mapping_summary,
)
from shared.reauction import collapse_reauction_lifecycles, reauction_context_for_listing
from shared.sold_comparables import select_km_aware_comparables
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro
from shared.validators import validate_sold_cars_df
from shared.valuation_display import (
    bid_display_parts,
    conservative_margin_percent,
    first_currency_value,
    recommended_max_bid_value,
)


st.set_page_config(page_title="AI Analysis (Curve)", layout="wide")
render_sidebar_navigation()
render_global_sidebar_filters()
inject_global_styles()
display_banner()
page_intro(
    "AI ANALYSIS",
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
        + ". Run the restricted dataset build and ensure curve data exists."
    )
    st.stop()


def _query_param_text(name: str) -> str:
    try:
        value = st.query_params.get(name, "")
    except Exception:
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


target_listing_url = _query_param_text("listing_url") or _query_param_text("url")
linked_listing_mode = bool(target_listing_url)


SPORT_TRIM_PATTERN = re.compile(r"\b(sport|sports|sx|zr|zrx)\b|sportivo|levin", re.IGNORECASE)
ENGINE_DEFECT_PATTERN = re.compile(r"engine noise observed|engine idling rough", re.IGNORECASE)
AUTOTRADER_OUTPUT = Path("autotrader_isolated/output/first_page_results.csv")
AUTOTRADER_RECENT_MARKET = Path("autotrader_isolated/output/autotrader_recent_market_tagged.csv")
AUTOTRADER_STATE = Path("autotrader_isolated/output/listing_state.csv")
CURVE_IMAGE_DIR = Path("curves/images")
STRUCTURAL_KEYWORDS = [
    "a pillar",
    "a-pillar",
    "b pillar",
    "b-pillar",
    "c pillar",
    "c-pillar",
    "chassis",
    "frame",
    "chassis rail",
    "frame rail",
    "cant rail",
    "apron",
]
REPLACEMENT_KEYWORDS = [
    "cracked bumper",
    "broken bumper",
    "torn",
    "missing",
    "requires replacement",
    "hole",
]
BOILERPLATE_PATTERNS = [
    r"\bplease refer to (the )?photos\b",
    r"\brefer to (the )?photos\b",
    r"\barrange inspection\b",
    r"\bview the condition of this vehicle\b",
]

DEFECT_PATTERNS: list[tuple[str, str, int]] = [
    # Mechanical (red)
    (r"\bengine rattle\b", "mechanical", 3),
    (r"\brattle on cold start\b", "mechanical", 3),
    (r"\bknock(ing)?\b", "mechanical", 3),
    (r"\bmisfire\b", "mechanical", 3),
    (r"\btransmission\b.*\bslip(ping)?\b", "mechanical", 3),
    (r"\bnot running\b|\bnon[- ]runner\b", "mechanical", 3),
    # Structural (red)
    (r"\b(a|b|c)[- ]?pillar\b", "structural", 3),
    (r"\bchassis\b|\bframe\b|\b(chassis|frame|cant) rail\b|\b(a|b|c)[- ]?pillar\b|\bapron\b", "structural", 3),
    # Hail = red / avoid
    (r"\bhail\b", "structural", 3),
    # Glass (orange)
    (r"\bwindscreen\b.*\bcrack(ed)?\b|\bcrack(ed)?\b.*\bwindscreen\b", "glass", 2),
    (r"\bwindscreen\b.*\bchip(ped)?\b|\bchip(ped)?\b.*\bwindscreen\b", "glass", 2),
    # Replacement (orange)
    (r"\b(headlight|tail ?light|taillight)\b.*\b(crack(ed)?|broken|missing)\b", "replacement", 2),
    (r"\b(bumper|bar)\b.*\b(crack(ed)?|broken|torn|missing)\b", "replacement", 2),
    (r"\bmirror\b.*\b(broken|missing)\b", "replacement", 2),
    (r"\bdoor\b.*\b(large dent|major dent)\b", "replacement", 2),
    (r"\bquarter panel\b", "replacement", 2),
    # Cosmetic (green)
    (r"\b(scratch(es)?|scrape(s)?|scuff(s)?|dent(s)?|stone chip(s)?|paint damage|mark(s)?)\b", "cosmetic", 1),
    (r"\b(paint|clear coat).*(peel|peeling|bubble|bubbling|sun damage|oxid|fade|fading)\b", "cosmetic", 1),
    (r"\b(peel(ing)?|bubble|bubbling|sun damage|oxidation)\b", "cosmetic", 1),
    # Interior (green/orange)
    (r"\bsteering wheel worn\b|\bworn steering wheel\b", "interior", 1),
    (r"\bgear knob\b.*\b(broken|missing)\b", "interior", 2),
    (r"\bseat\b.*\b(stain|stains|stained)\b|\b(stain|stains|stained)\b.*\bseat\b", "interior", 1),
    (r"\bseat\b.*\b(torn|tear|ripped)\b|\b(torn|tear|ripped)\b.*\bseat\b", "interior", 1),
]


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


def _expected_finish_display_parts(row: pd.Series) -> tuple[str, str]:
    raw_expected = parse_currency(row.get("expected_auction_price"))
    bid_basis = parse_currency(row.get("expected_auction_bid_basis"))
    display_value = row.get("expected_auction_bid_basis") or row.get("expected_auction_price")
    display_text = _format_price_text(display_value)
    cap_status = _expected_finish_cap_status(row)
    status_text = cap_status or _safe_text(row.get("bid_status"), fallback="Unknown")
    if (
        bid_basis is not None
        and raw_expected is not None
        and bid_basis > raw_expected
    ):
        status_text = f"{status_text}; using current bid"
    if _truthy(row.get("no_edge")):
        status_text = f"{status_text}; no edge now"
    return display_text, status_text


def _expected_finish_cap_status(row: pd.Series) -> str:
    expected_value = parse_currency(row.get("expected_auction_bid_basis"))
    if expected_value is None:
        expected_value = parse_currency(row.get("expected_auction_price"))
    max_bid = parse_currency(row.get("recommended_max_bid"))
    if max_bid is None:
        max_bid = parse_currency(row.get("max_bid_value"))
    if expected_value is None or max_bid is None or max_bid <= 0:
        return ""
    gap = expected_value - max_bid
    if gap > 0:
        return f"Projected over max cap by {_format_currency_value(gap)}"
    return "Projected within max cap"


def _max_bid_safety_text(row: pd.Series) -> str:
    safety_text = _safe_text(row.get("hard_max_safety"), fallback="Unknown")
    if safety_text in {"Unknown", "N/A"}:
        return safety_text
    return f"{safety_text} at max"


def _format_odometer(value: object) -> str:
    odo_val = parse_numeric(value)
    if odo_val is None or (isinstance(odo_val, float) and pd.isna(odo_val)):
        return "N/A"
    return f"{int(round(odo_val)):,} km"


def _curve_confidence_label(value: Optional[float]) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Unknown"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "Unknown"
    if numeric >= 0.7:
        return "High"
    if numeric >= 0.5:
        return "Medium"
    return "Low"


def _curve_key_for_row(row: pd.Series) -> str:
    curve_tag = _safe_text(row.get("curve_tag"), fallback="").strip()
    if curve_tag:
        return curve_tag
    return resolve_curve_canonical_tag(_safe_text(row.get("canonical_tag"), fallback="").strip())


def _curve_image_filename(canonical_tag: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", canonical_tag).strip("_")
    return f"{slug}.png" if slug else ""


def _find_curve_year_bounds(
    curves_df: pd.DataFrame, canonical_tag: str, year: Optional[int]
) -> tuple[Optional[int], Optional[int]]:
    if curves_df.empty or not canonical_tag or year is None:
        return None, None
    curve_tag = resolve_curve_canonical_tag(canonical_tag)
    subset = curves_df[curves_df["canonical_tag"] == curve_tag].copy()
    if subset.empty or "anchor_year" not in subset.columns:
        return None, None
    years = sorted({int(y) for y in subset["anchor_year"].dropna()})
    if not years:
        return None, None
    if year <= years[0]:
        return years[0], years[0]
    if year >= years[-1]:
        return years[-1], years[-1]
    lower = years[0]
    upper = years[-1]
    for start, end in zip(years, years[1:]):
        if start <= year <= end:
            lower, upper = start, end
            break
    return lower, upper


def _clean_price_km_points(points: list[tuple[float, float]] | None) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []
    for km_value, price_value in points or []:
        try:
            km_float = float(km_value)
            price_float = float(price_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(km_float) or not math.isfinite(price_float):
            continue
        if km_float <= 0 or price_float <= 0:
            continue
        cleaned.append((km_float, price_float))
    return cleaned


def _linear_fit_line_points(points: list[tuple[float, float]] | None) -> list[tuple[float, float]]:
    cleaned = _clean_price_km_points(points)
    if len(cleaned) < 2:
        return []

    km_values = [pt[0] for pt in cleaned]
    price_values = [pt[1] for pt in cleaned]
    if len(set(km_values)) < 2:
        return []

    km_mean = sum(km_values) / len(km_values)
    price_mean = sum(price_values) / len(price_values)
    denominator = sum((km_value - km_mean) ** 2 for km_value in km_values)
    if denominator <= 0:
        return []

    slope = sum(
        (km_value - km_mean) * (price_value - price_mean)
        for km_value, price_value in cleaned
    ) / denominator
    intercept = price_mean - slope * km_mean
    km_min = min(km_values)
    km_max = max(km_values)
    return [
        (km_min, slope * km_min + intercept),
        (km_max, slope * km_max + intercept),
    ]


def _plot_sold_comparable_overlay(sold_points: list[tuple[float, float]] | None) -> None:
    import matplotlib.pyplot as plt

    cleaned = _clean_price_km_points(sold_points)
    if not cleaned:
        return

    sold_km = [pt[0] for pt in cleaned]
    sold_price = [pt[1] for pt in cleaned]
    plt.scatter(
        sold_km,
        sold_price,
        color="#6b7280",
        alpha=0.65,
        s=28,
        label="Grays sold comps",
    )

    fit_line = _linear_fit_line_points(cleaned)
    if fit_line:
        fit_km = [pt[0] for pt in fit_line]
        fit_price = [pt[1] for pt in fit_line]
        plt.plot(
            fit_km,
            fit_price,
            color="#111827",
            linestyle="--",
            linewidth=2,
            alpha=0.9,
            label="Sold best fit",
        )


def _render_interpolated_curve_plot(
    curves_df: pd.DataFrame,
    canonical_tag: str,
    year: int,
    km: Optional[float],
    lower_year: int,
    upper_year: int,
    autotrader_points: list[tuple[float, float]] | None = None,
    sold_points: list[tuple[float, float]] | None = None,
) -> bool:
    if km is None:
        return False
    lower_points = get_curve_points(curves_df, canonical_tag, lower_year)
    upper_points = get_curve_points(curves_df, canonical_tag, upper_year)
    if not lower_points or not upper_points:
        return False

    import matplotlib.pyplot as plt

    lower_km = [pt[0] for pt in lower_points]
    lower_price = [pt[1] for pt in lower_points]
    upper_km = [pt[0] for pt in upper_points]
    upper_price = [pt[1] for pt in upper_points]

    lower_val = interpolate_price_by_km(lower_points, km)
    upper_val = interpolate_price_by_km(upper_points, km)
    interp_val = None
    if lower_val is not None and upper_val is not None and upper_year != lower_year:
        ratio = (year - lower_year) / float(upper_year - lower_year)
        interp_val = lower_val + ratio * (upper_val - lower_val)

    plt.figure(figsize=(10, 4))
    plt.plot(lower_km, lower_price, color="#9aa0a6", linewidth=2, label=f"{lower_year}")
    plt.plot(upper_km, upper_price, color="#5f6368", linewidth=2, label=f"{upper_year}")
    if lower_val is not None:
        plt.scatter([km], [lower_val], color="#9aa0a6", s=25)
    if upper_val is not None:
        plt.scatter([km], [upper_val], color="#5f6368", s=25)
    if interp_val is not None:
        plt.scatter([km], [interp_val], color="#1f77b4", s=50, label=f"{year} (interp)")
    if autotrader_points:
        auto_km = [pt[0] for pt in autotrader_points]
        auto_price = [pt[1] for pt in autotrader_points]
        plt.scatter(auto_km, auto_price, color="#ff7f0e", s=35, label="Autotrader (year match)")
    _plot_sold_comparable_overlay(sold_points)

    plt.xlabel("Kilometres")
    plt.ylabel("Resale price ($)")
    plt.grid(alpha=0.2)
    plt.legend(loc="best", frameon=False)
    plt.tight_layout()
    st.pyplot(plt.gcf(), clear_figure=True, use_container_width=True)
    return True


def _render_single_curve_plot(
    curves_df: pd.DataFrame,
    canonical_tag: str,
    year: int,
    km: Optional[float],
    autotrader_points: list[tuple[float, float]] | None = None,
    sold_points: list[tuple[float, float]] | None = None,
) -> bool:
    if km is None:
        return False
    points = get_curve_points(curves_df, canonical_tag, year)
    if not points:
        return False
    import matplotlib.pyplot as plt
    x = [pt[0] for pt in points]
    y = [pt[1] for pt in points]
    val = interpolate_price_by_km(points, km)
    plt.figure(figsize=(10, 4))
    plt.plot(x, y, color="#5f6368", linewidth=2, label=str(year))
    if val is not None:
        plt.scatter([km], [val], color="#1f77b4", s=50, label=f"{year}")
    if autotrader_points:
        auto_km = [pt[0] for pt in autotrader_points]
        auto_price = [pt[1] for pt in autotrader_points]
        plt.scatter(auto_km, auto_price, color="#ff7f0e", s=35, label="Autotrader (year match)")
    _plot_sold_comparable_overlay(sold_points)
    plt.xlabel("Kilometres")
    plt.ylabel("Resale price ($)")
    plt.grid(alpha=0.2)
    plt.legend(loc="best", frameon=False)
    plt.tight_layout()
    st.pyplot(plt.gcf(), clear_figure=True, use_container_width=True)
    return True


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


def _display_action_label(action: object) -> str:
    return action_display_parts(action)[0]


def _display_action_detail(action: object) -> str:
    return action_display_parts(action)[1]


def _display_profit_label(label: object) -> str:
    label_text = _safe_text(label, fallback="Unknown").strip()
    mapping = {
        "Strong": "High margin",
        "Good": "Good margin",
        "Conditional": "Okay margin",
        "Thin": "Thin margin",
        "No edge": "No edge",
        "Unknown": "Unknown",
    }
    return mapping.get(label_text, label_text)


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


def _get_condition_text(row: pd.Series) -> str:
    normalized = _safe_text(row.get("normalized_condition_text"), fallback="").strip()
    if normalized:
        return normalized
    return _safe_text(row.get("general_condition"), fallback="").strip()


def _shorten_text(value: object, width: int = 72) -> str:
    text = _safe_text(value, fallback="")
    if not text:
        return "N/A"
    return textwrap.shorten(text, width=width, placeholder="...")


def _norm_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _detect_keywords(text: str, keywords: list[str]) -> list[str]:
    if not text:
        return []
    lowered = text.lower()
    hits = [keyword for keyword in keywords if keyword in lowered]
    return sorted(set(hits))


def _bool_label(value: object) -> str:
    return "yes" if _truthy(value) else "no"


def _split_condition_notes(notes: str) -> list[str]:
    if not notes:
        return []
    text = str(notes).replace("\r\n", "\n")
    # Normalize common separators into newlines for clean per-defect lines.
    text = re.sub(r"\s+\|\s+|\s+-\s+", "\n", text)
    text = text.replace("•", "\n")
    text = text.replace(";", "\n")
    # Insert spaces between jammed words (e.g., "BrokenInterior").
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    # Split on sentence boundaries even without a space after the period.
    text = re.sub(r"\.(?=[A-Z])", ".\n", text)
    # Split on common section labels.
    text = re.sub(
        r"\b(Interior|Exterior|Engine|Mechanical|Body|Paint|Panel|Glass|Windscreen)[:]",
        r"\n\1:",
        text,
    )
    parts = re.split(r"[\n\r]+|(?<=[.!?])\s+", text)
    seen: set[str] = set()
    cleaned: list[str] = []
    for part in parts:
        norm = _norm_text(part)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        cleaned.append(part.strip())
    return cleaned


def _bucket_details_from_notes(
    notes: str,
) -> tuple[dict[str, int], dict[str, list[str]], list[str]]:
    severities = {
        "cosmetic": 0,
        "glass": 0,
        "replacement": 0,
        "structural": 0,
        "mechanical": 0,
        "interior": 0,
    }
    bucket_lines = {key: [] for key in severities}
    lines = _split_condition_notes(notes)
    if lines:
        lines = [
            line
            for line in lines
            if not any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in BOILERPLATE_PATTERNS)
        ]
    if not lines:
        return severities, bucket_lines, []
    for pattern, bucket, level in DEFECT_PATTERNS:
        for line in lines:
            if re.search(pattern, line, flags=re.IGNORECASE):
                severities[bucket] = max(severities[bucket], level)
                if line not in bucket_lines[bucket]:
                    bucket_lines[bucket].append(line)
    matched = set()
    for items in bucket_lines.values():
        matched.update(items)
    unmatched = [line for line in lines if line not in matched]
    return severities, bucket_lines, unmatched


def _rego_ok(row: dict[str, object]) -> bool:
    expiry = str(row.get("rego_expiry", "") or "").lower()
    rego_no = str(row.get("rego_no", "") or "").strip()
    if "unregistered" in expiry or "sold unregistered" in expiry:
        return False
    if rego_no:
        return True
    return bool(expiry)


def _resale_value_for_repairs(row) -> Optional[float]:
    # Same vehicle-value figure the live pipeline passes to assess_repairs(), so the
    # cosmetic-cap/verdict-gate scaling shown here matches what actually drove the
    # stored recommended_max_bid/computed_verdict for this listing. Falls back through
    # a few resale field names since callers pass either a pd.Series row or a plain
    # dict (row.to_dict()) with the same keys.
    getter = row.get
    return first_currency_value(
        getter("resale_mid_value"),
        getter("resale_mid"),
        getter("expected_sale"),
        getter("curve_adjusted"),
    )


def build_defect_profile(row: dict[str, object]) -> dict[str, object]:
    notes = row.get("normalized_condition_text") or row.get("general_condition", "") or ""
    adas_windscreen = bool(
        row.get("adas_windscreen") or row.get("windscreen_adas") or row.get("windshield_adas")
    )
    assessment = assess_repairs(
        notes,
        adas_windscreen=adas_windscreen,
        vehicle_value=_resale_value_for_repairs(row),
        vehicle_class=vehicle_class_for_listing(row),
    )
    bucket_lines = {
        "cosmetic": [],
        "glass": [],
        "replacement": [],
        "structural": [],
        "mechanical": [],
        "interior": [],
    }
    unmatched: list[str] = []
    matched_pills: set[str] = set()
    for fragment in assessment.fragments:
        line = fragment.original_text
        if not line:
            continue
        matched_pills.update(fragment.pills)
        if fragment.status == "unclassified":
            unmatched.append(line)
            continue
        if fragment.status == "ignored":
            continue
        if fragment.hard_avoid_reason == "mechanical" or "MECHANICAL" in fragment.pills:
            bucket_lines["mechanical"].append(line)
        elif fragment.hard_avoid_reason == "structural" or "STRUCTURAL" in fragment.pills:
            bucket_lines["structural"].append(line)
        elif fragment.category == "glass" or "GLASS" in fragment.pills:
            bucket_lines["glass"].append(line)
        elif fragment.category == "replacement" or "PANEL_REPLACE" in fragment.pills:
            bucket_lines["replacement"].append(line)
        elif fragment.category == "interior":
            bucket_lines["interior"].append(line)
        elif fragment.category == "cosmetic" or "COSMETIC_PANEL" in fragment.pills:
            bucket_lines["cosmetic"].append(line)

    for key, values in bucket_lines.items():
        bucket_lines[key] = list(dict.fromkeys(values))
    unmatched = list(dict.fromkeys(unmatched))

    severities = {
        "cosmetic": min(3, int(assessment.cosmetic_panels or 0)),
        "glass": 2 if assessment.glass_cost > 0 or "GLASS" in assessment.pills else 0,
        "replacement": 2 if assessment.replacement_cost > 0 or "PANEL_REPLACE" in assessment.pills else 0,
        "structural": 3 if assessment.hard_avoid_reason == "structural" or "STRUCTURAL" in assessment.pills else 0,
        "mechanical": 3 if assessment.hard_avoid_reason == "mechanical" or "MECHANICAL" in assessment.pills else 0,
        "interior": min(2, len(bucket_lines["interior"])),
    }
    profile: dict[str, object] = {
        "rego_ok": _rego_ok(row),
        "spare_key_ok": _truthy(row.get("spare_key")),
        "owners_manual_ok": _truthy(row.get("owners_manual")),
        "service_history_ok": _truthy(row.get("service_history")),
        "engine_turns_over_ok": _truthy(row.get("engine_turns_over")),
        **severities,
        "bucket_lines": bucket_lines,
        "unmatched_lines": unmatched,
        "repair_cost": int(assessment.total_cost or 0),
        "repair_pills": sorted(set(assessment.pills) | matched_pills),
        "repair_hard_avoid": bool(assessment.hard_avoid),
        "repair_hard_avoid_reason": assessment.hard_avoid_reason or "",
    }
    return profile


def similarity_score(a: dict[str, object], b: dict[str, object]) -> int:
    score = 0
    score += 100 * abs(int(a["mechanical"]) - int(b["mechanical"]))
    score += 60 * abs(int(a["structural"]) - int(b["structural"]))
    score += 30 * abs(int(a["replacement"]) - int(b["replacement"]))
    score += 20 * abs(int(a["glass"]) - int(b["glass"]))
    score += 8 * abs(int(a["cosmetic"]) - int(b["cosmetic"]))
    score += 6 * abs(int(a["interior"]) - int(b["interior"]))
    a_cost = int(a.get("repair_cost", 0) or 0)
    b_cost = int(b.get("repair_cost", 0) or 0)
    score += min(60, abs(a_cost - b_cost) // 250)
    a_pills = set(a.get("repair_pills", []) or [])
    b_pills = set(b.get("repair_pills", []) or [])
    score += 10 * len(a_pills.symmetric_difference(b_pills))
    if bool(a.get("repair_hard_avoid")) != bool(b.get("repair_hard_avoid")):
        score += 80
    for key in (
        "rego_ok",
        "spare_key_ok",
        "owners_manual_ok",
        "service_history_ok",
        "engine_turns_over_ok",
    ):
        score += 3 if bool(a.get(key)) != bool(b.get(key)) else 0
    return score


def match_quality_from_score(score: int) -> str:
    if score <= 15:
        return "Strong"
    if score <= 35:
        return "OK"
    return "Weak"


def _defects_compact(profile: dict[str, object]) -> str:
    repair_cost = int(profile.get("repair_cost", 0) or 0)
    hard_reason = _safe_text(profile.get("repair_hard_avoid_reason"), fallback="")
    hard_text = f" {hard_reason.upper()}" if hard_reason else ""
    return (
        f"C{int(profile['cosmetic'])} "
        f"G{int(profile['glass'])} "
        f"R{int(profile['replacement'])} "
        f"S{int(profile['structural'])} "
        f"M{int(profile['mechanical'])} "
        f"I{int(profile['interior'])} "
        f"${repair_cost:,}{hard_text}"
    )


def _severity_pill_html(value: int, tooltip: str = "") -> str:
    label = str(value)
    if value <= 0:
        cls = "chip"
    elif value == 1:
        cls = "chip good"
    elif value == 2:
        cls = "chip warn"
    else:
        cls = "chip danger"
    title = f' title="{html.escape(tooltip)}"' if tooltip else ""
    return f'<span class="{cls}"{title}>{label}</span>'


def _severity_label_pill_html(label: str, value: int, tooltip: str = "") -> str:
    if value <= 0:
        cls = "chip"
    elif value == 1:
        cls = "chip good"
    elif value == 2:
        cls = "chip warn"
    else:
        cls = "chip danger"
    title = f' title="{html.escape(tooltip)}"' if tooltip else ""
    return f'<span class="{cls}"{title}>{html.escape(label)}</span>'


def _bool_pill_html(value: object, tooltip: str = "") -> str:
    cls = "chip good" if _truthy(value) else "chip danger"
    label = "yes" if _truthy(value) else "no"
    title = f' title="{html.escape(tooltip)}"' if tooltip else ""
    return f'<span class="{cls}"{title}>{label}</span>'


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

    left_key = _norm_fuel(left)
    right_key = _norm_fuel(right)
    if not left_key or not right_key:
        return True
    return left_key == right_key or left_key in right_key or right_key in left_key


def _trans_match(left: object, right: object) -> bool:
    def _norm_trans(value: object) -> str:
        key = _norm_key(value)
        if key in {"auto", "automatic", "cvt", "sportsautomatic", "sptsauto"}:
            return "auto"
        if key in {"manual"}:
            return "manual"
        return key

    left_key = _norm_trans(left)
    right_key = _norm_trans(right)
    if not left_key or not right_key:
        return True
    return left_key == right_key or left_key in right_key or right_key in left_key


def _body_match(left: object, right: object) -> bool:
    def _norm_body(value: object) -> str:
        key = _norm_key(value)
        if key in {"suv", "wagon", "stationwagon", "crossover"}:
            return "suv_wagon"
        if key in {"hatch", "hatchback"}:
            return "hatchback"
        return key

    left_key = _norm_body(left)
    right_key = _norm_body(right)
    if not left_key or not right_key:
        return True
    return left_key == right_key or left_key in right_key or right_key in left_key


def _score_autotrader_matches(
    listing_row: pd.Series,
    curve_tag: str,
    *,
    limit: int = 3,
) -> tuple[pd.DataFrame, dict[str, int]]:
    if autotrader_df.empty or not curve_tag:
        return pd.DataFrame(), {"total": 0}
    target_km = parse_numeric(listing_row.get("odometer_reading"))
    if target_km is None or target_km <= 0:
        return pd.DataFrame(), {"total": 0}

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

    listing_tag = _safe_text(listing_row.get("canonical_tag"), fallback="").strip()
    if listing_tag == UNCLASSIFIED:
        listing_tag = ""

    stats = {
        "total": len(autotrader_df),
        "make_match": 0,
        "group_match": 0,
        "fuel_trans_body": 0,
        "km_window": 0,
    }
    rows: list[dict[str, object]] = []
    for _, candidate in autotrader_df.iterrows():
        candidate_make = _norm_key(candidate.get("make"))
        if listing_make and candidate_make != listing_make:
            continue
        stats["make_match"] += 1
        candidate_tag = _safe_text(candidate.get("canonical_tag"), fallback="").strip()
        if candidate_tag == UNCLASSIFIED:
            candidate_tag = ""
        candidate_tag = resolve_curve_canonical_tag(candidate_tag) if candidate_tag else ""
        if not candidate_tag or candidate_tag != curve_tag:
            continue
        stats["group_match"] += 1
        if not _fuel_match(listing_fuel, candidate.get("fuel_type")):
            continue
        if not _trans_match(listing_trans, candidate.get("transmission")):
            continue
        if not _body_match(listing_body, candidate.get("body_type")):
            continue
        stats["fuel_trans_body"] += 1

        candidate_km = candidate.get("odometer_value")
        if candidate_km is None or pd.isna(candidate_km):
            continue
        km_diff = abs(float(candidate_km) - float(target_km))
        if km_diff > 100000:
            continue
        stats["km_window"] += 1
        km_score = min(km_diff / 100000.0, 1.0)

        candidate_state = extract_state(candidate.get("location"))
        state_penalty = 0.05 if listing_state and candidate_state and listing_state != candidate_state else 0.0

        age_penalty = 0.0
        if listing_year is not None:
            candidate_year = candidate.get("year_int")
            if candidate_year is not None and not pd.isna(candidate_year):
                year_diff = abs(int(candidate_year) - listing_year)
                if year_diff == 1:
                    age_penalty = 0.05
                elif year_diff > 1:
                    age_penalty = 0.15

        total_score = km_score + state_penalty + age_penalty
        if total_score <= 0.10:
            quality = "Strong"
        elif total_score <= 0.22:
            quality = "OK"
        else:
            quality = "Weak"

        rows.append(
            {
                "year": candidate.get("year"),
                "make": candidate.get("make"),
                "model": candidate.get("model"),
                "variant": candidate.get("variant"),
                "price": candidate.get("price"),
                "odometer": candidate.get("odometer"),
                "odometer_value": candidate.get("odometer_value"),
                "location": candidate.get("location"),
                "transmission": candidate.get("transmission"),
                "fuel_type": candidate.get("fuel_type"),
                "rego": candidate.get("rego"),
                "url": candidate.get("url"),
                "price_value": candidate.get("price_value"),
                "status": candidate.get("status"),
                "first_seen": candidate.get("first_seen"),
                "last_seen": candidate.get("last_seen"),
                "last_price_date": candidate.get("last_price_date"),
                "sold_date": candidate.get("sold_date"),
                "match_score": total_score,
                "match_quality": quality,
            }
        )

    if not rows:
        return pd.DataFrame(), stats
    scored = pd.DataFrame(rows).sort_values(by=["match_score"], ascending=True)
    return scored.head(max(1, int(limit))).reset_index(drop=True), stats


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
        price_value = parse_currency(match.get("price_value") or match.get("price"))
        if price_value is None or price_value <= 0:
            continue
        near_curve = abs(price_value - resale_value) / resale_value <= 0.10
        if not near_curve:
            continue
        near_curve_count += 1
        near_prices.append(float(price_value))

        first_seen = pd.to_datetime(match.get("first_seen"), errors="coerce", utc=True)
        last_seen = pd.to_datetime(match.get("last_seen"), errors="coerce", utc=True)
        sold_date = pd.to_datetime(match.get("sold_date"), errors="coerce", utc=True)
        status = _safe_text(match.get("status"), fallback="").strip().lower()

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

    median_days = None
    if observed_days:
        median_days = float(pd.Series(observed_days).median())
    median_near_price = None
    if near_prices:
        median_near_price = float(pd.Series(near_prices).median())

    return {
        "matched_count": int(len(matches)),
        "fast_clear_count": int(fast_clear_count),
        "stale_active_count": int(stale_active_count),
        "near_curve_count": int(near_curve_count),
        "median_days_listed": median_days,
        "median_near_curve_price": median_near_price,
    }


def _condition_summary_sections(row: pd.Series) -> tuple[list[dict[str, object]], str]:
    raw_notes = _safe_text(row.get("general_condition"), fallback="").strip()
    display_notes = _safe_text(row.get("normalized_condition_text"), fallback="").strip() or raw_notes
    adas_windscreen = bool(
        row.get("adas_windscreen") or row.get("windscreen_adas") or row.get("windshield_adas")
    )
    assessment = assess_repairs(
        display_notes,
        adas_windscreen=adas_windscreen,
        vehicle_value=_resale_value_for_repairs(row),
        vehicle_class=vehicle_class_for_listing(row),
    )
    _, bucket_lines, _ = _bucket_details_from_notes(display_notes)
    sections: list[dict[str, object]] = []

    cosmetic_panels = max(int(assessment.cosmetic_panels or 0), 0)
    cosmetic_panels_capped = min(cosmetic_panels, PANEL_CAP)
    if cosmetic_panels_capped > 0:
        panels_label = "panel" if cosmetic_panels_capped == 1 else "panels"
        cosmetic_cost = cosmetic_panels_capped * PANEL_RATE
        cosmetic_lines = bucket_lines.get("cosmetic", [])
        sections.append(
            {
                "title": "Cosmetic damage",
                "bullets": (cosmetic_lines or ["Multiple dents/scratches/scuffs (summarised from notes)"])
                + [f"Assumed {panels_label}: {cosmetic_panels_capped} (cap {PANEL_CAP})"],
                "cost_line": f"Cost applied: ${cosmetic_cost:,} (panel rate ${PANEL_RATE:,})",
            }
        )
    else:
        sections.append(
            {
                "title": "Cosmetic damage",
                "bullets": bucket_lines.get("cosmetic", []) or ["No cosmetic issues flagged."],
            }
        )

    structural_hits = _detect_keywords(display_notes, STRUCTURAL_KEYWORDS)
    replacement_hits = _detect_keywords(display_notes, REPLACEMENT_KEYWORDS)
    replacement_present = bool(assessment.replacement_cost > 0) or "PANEL_REPLACE" in assessment.pills
    structural_bullets: list[str] = []
    if structural_hits:
        structural_bullets.append("Structural indicators: " + ", ".join(structural_hits))
    if replacement_hits:
        structural_bullets.append("Replacement indicators: " + ", ".join(replacement_hits))
    if replacement_present and "Replacement indicators" not in " ".join(structural_bullets):
        structural_bullets.append("Replacement flagged by condition parser")
    structural_lines = bucket_lines.get("structural", [])
    replacement_lines = bucket_lines.get("replacement", [])
    if structural_lines:
        structural_bullets.extend(structural_lines)
    if replacement_lines:
        structural_bullets.extend(replacement_lines)
    if structural_bullets:
        sections.append(
            {
                "title": "Structural / panel replacement",
                "bullets": structural_bullets,
                "impact_line": "Impact: Max-bid risk penalty applied.",
            }
        )
    else:
        sections.append(
            {
                "title": "Structural / panel replacement",
                "bullets": ["No structural/replacement indicators detected."],
            }
        )

    glass_present = bool(assessment.glass_cost > 0) or "GLASS" in assessment.pills
    if glass_present:
        glass_cost = WINDSCREEN_ADAS if adas_windscreen else WINDSCREEN_STD
        glass_lines = bucket_lines.get("glass", [])
        sections.append(
            {
                "title": "Glass",
                "bullets": glass_lines or ["Windscreen issue flagged (chip/crack)."],
                "cost_line": f"Cost applied: ${glass_cost:,}" + (" (ADAS)" if adas_windscreen else ""),
            }
        )
    else:
        sections.append(
            {
                "title": "Glass",
                "bullets": bucket_lines.get("glass", []) or ["No glass issues flagged."],
            }
        )

    mechanical_hit = assessment.hard_avoid or "MECHANICAL" in assessment.pills
    if mechanical_hit:
        mechanical_lines = bucket_lines.get("mechanical", [])
        sections.append(
            {
                "title": "Mechanical",
                "bullets": mechanical_lines or ["Mechanical fault detected."],
                "impact_line": "Impact: HARD AVOID.",
            }
        )
    else:
        sections.append(
            {
                "title": "Mechanical",
                "bullets": bucket_lines.get("mechanical", []) or ["No mechanical faults reported (does not guarantee none)."],
            }
        )

    interior_lines = bucket_lines.get("interior", [])
    if interior_lines:
        sections.append(
            {
                "title": "Interior",
                "bullets": interior_lines,
            }
        )
    else:
        sections.append(
            {
                "title": "Interior",
                "bullets": ["No interior issues flagged."],
            }
        )

    admin_bullets: list[str] = []
    rego_status = _rego_status(row.get("rego_expiry"), row.get("rego_no"))
    if rego_status == "Unregistered":
        admin_bullets.append("Unregistered")
    if "rust" in _norm_text(raw_notes):
        admin_bullets.append("Rust noted")
    if "UNKNOWN" in assessment.pills:
        admin_bullets.append("Unknown condition/photos")
    admin_bullets.extend(_parse_risk_flags(row.get("risk_flags")))
    admin_bullets = sorted({bullet for bullet in admin_bullets if bullet})
    if admin_bullets:
        sections.append(
            {
                "title": "Admin / risk flags",
                "bullets": admin_bullets,
                "impact_line": "Impact: Included in risk buffer / max-bid reduction.",
            }
        )
    else:
        sections.append(
            {
                "title": "Admin / risk flags",
                "bullets": ["No admin/risk flags detected."],
            }
        )

    total_deduction = int(assessment.total_cost or 0)
    high_deduction = int(assessment.total_cost_high or assessment.total_cost or 0)
    low_deduction = int(assessment.total_cost_low or 0)
    if assessment.hard_avoid:
        hard_reason = _safe_text(assessment.hard_avoid_reason, fallback="condition").replace("_", " ")
        sections.append(
            {
                "title": "Repair / risk decision",
                "bullets": [
                    f"Hard avoid: {hard_reason}.",
                    "Proxy max is blocked rather than reduced by a normal repair allowance.",
                ],
                "cost_line": f"Hard-avoid reserve: ${total_deduction:,}",
            }
        )
    elif total_deduction > 0:
        sections.append(
            {
                "title": "Repair / risk allowance",
                "bullets": [
                    "Likely allowance is shown separately from the conservative max-bid deduction.",
                ],
                "cost_line": (
                    f"Likely: ${total_deduction:,}"
                    f" (range ${low_deduction:,}-${high_deduction:,}; max-bid deduction uses ${high_deduction:,})"
                ),
            }
        )

    return sections, raw_notes


def _render_repair_fragment_records(records: list[dict[str, object]]) -> None:
    for record in records:
        original = _safe_text(record.get("original_text"), fallback="")
        status = _safe_text(record.get("status"), fallback="unclassified")
        category = _safe_text(record.get("category"), fallback="unclassified")
        defects = _safe_text(record.get("canonical_defects"), fallback="")
        pills = _safe_text(record.get("pills"), fallback="")
        cost = parse_currency(record.get("cost_estimate"))
        reasons = _safe_text(record.get("reasons"), fallback="")
        meta = [f"status: {status}", f"category: {category}"]
        if defects:
            meta.append(f"match: {defects}")
        if pills:
            meta.append(f"pills: {pills}")
        if cost and cost > 0:
            meta.append(f"cost: {_format_currency_value(cost)}")
        st.markdown(f"- **{html.escape(original)}**")
        st.caption(" | ".join(meta))
        if reasons:
            st.caption(reasons)


def _listing_title(row: pd.Series) -> str:
    parts = [
        _safe_text(row.get("year"), fallback=""),
        _safe_text(row.get("make"), fallback=""),
        _safe_text(row.get("model"), fallback=""),
        _safe_text(row.get("variant"), fallback=""),
    ]
    return " ".join(part for part in parts if part) or "Unknown vehicle"


def _render_repair_mapping_status(
    row: pd.Series,
    fragment_records: list[dict[str, object]],
    display_notes: str,
) -> None:
    summary = repair_mapping_summary(fragment_records)
    total = int(summary.get("total", 0) or 0)
    needs_review = list(summary.get("needs_review_records", []) or [])
    unresolved = list(summary.get("unresolved_records", []) or [])
    mapped = int(summary.get("mapped_count", 0) or 0)

    if not fragment_records:
        st.info("Repair mapping: no condition fragments found.")
        return

    if summary.get("pass"):
        st.success(f"Repair mapping pass: {mapped}/{total} fragments identified.")
        return

    if needs_review:
        appended = append_live_review_items(
            needs_review,
            vehicle=_listing_title(row),
            url=_safe_text(row.get("url"), fallback=""),
            condition_notes=display_notes,
        )
        suffix = f" Added {appended} item(s) to Repair Review." if appended else ""
        st.warning(
            f"Repair mapping needs review: {len(needs_review)} new/unmapped fragment(s); "
            f"{len(unresolved)} reviewed unresolved fragment(s).{suffix}"
        )
        with st.expander("Unmapped repair fragments", expanded=True):
            for record in needs_review:
                st.write(f"- {safe_fragment_text(record)}")
    else:
        st.warning(
            f"Repair mapping reviewed but unresolved: {len(unresolved)} fragment(s) are saved as unclassified."
        )
    if unresolved:
        with st.expander("Reviewed unresolved fragments", expanded=False):
            for record in unresolved:
                st.write(f"- {safe_fragment_text(record)}")


def safe_fragment_text(record: dict[str, object]) -> str:
    text = _safe_text(record.get("original_text"), fallback="")
    status = _safe_text(record.get("status"), fallback="unclassified")
    category = _safe_text(record.get("category"), fallback="unclassified")
    return f"{text} ({status}, {category})" if text else f"{status}, {category}"


def _render_condition_summary(row: pd.Series) -> None:
    sections, raw_notes = _condition_summary_sections(row)
    display_notes = _safe_text(row.get("normalized_condition_text"), fallback="").strip() or raw_notes
    adas_windscreen = bool(
        row.get("adas_windscreen") or row.get("windscreen_adas") or row.get("windshield_adas")
    )
    assessment = assess_repairs(
        display_notes,
        adas_windscreen=adas_windscreen,
        vehicle_value=_resale_value_for_repairs(row),
        vehicle_class=vehicle_class_for_listing(row),
    )
    st.markdown("**Condition summary**")
    for section in sections:
        st.markdown(f"**{section['title']}**")
        for bullet in section.get("bullets", []):
            st.write(f"- {bullet}")
        cost_line = section.get("cost_line")
        if cost_line:
            st.write(f"**{cost_line}**")
        impact_line = section.get("impact_line")
        if impact_line:
            st.write(f"*{impact_line}*")
        st.write("")
    fragment_records = repair_fragments_to_records(assessment)
    _render_repair_mapping_status(row, fragment_records, display_notes)
    if fragment_records:
        st.markdown("**Repair split / dictionary match**")
        _render_repair_fragment_records(fragment_records)
    with st.expander("Source condition notes (verbatim)", expanded=False):
        if not raw_notes:
            st.write("(none)")
        else:
            lines = _split_condition_notes(raw_notes)
            if not lines:
                st.write(raw_notes)
            else:
                st.markdown("\n".join(f"- {line}" for line in lines))


def _render_curve_section(row: pd.Series) -> None:
    curve_tag = _curve_key_for_row(row)
    resale_value = _compute_resale_value(row)
    resale_display = _format_currency_value(resale_value)
    km_display = _format_odometer(row.get("odometer_reading"))
    confidence_label = _curve_confidence_label(row.get("confidence"))
    listing_year = _safe_int(row.get("year"))
    autotrader_points: list[tuple[float, float]] = []
    sold_points: list[tuple[float, float]] = []

    st.markdown("**Resale Curve (Carsales)**")
    if curve_tag:
        st.caption(f"{curve_tag}")
    st.write(f"Estimated resale @ {km_display} → **{resale_display}**  |  Confidence: **{confidence_label}**")

    if not curve_tag:
        st.info("Curve image not available (missing curve key).")
        return

    if listing_year is not None:
        matches, _ = _score_autotrader_matches(row, curve_tag, limit=50)
        if not matches.empty and "year" in matches.columns:
            year_matches = matches[pd.to_numeric(matches["year"], errors="coerce") == listing_year]
            for _, m in year_matches.iterrows():
                km_val = m.get("odometer_value")
                if km_val is None or pd.isna(km_val):
                    km_val = parse_numeric(m.get("odometer"))
                price_val = m.get("price_value")
                if km_val is not None and price_val is not None and not pd.isna(km_val) and not pd.isna(price_val):
                    autotrader_points.append((float(km_val), float(price_val)))

    if curve_tag and "sold_df" in globals():
        sold_subset = _select_sold_subset(sold_df, curve_tag, listing_year)
        for _, sold_row in sold_subset.iterrows():
            km_val = sold_row.get("odometer_numeric")
            if km_val is None or pd.isna(km_val):
                km_val = parse_numeric(sold_row.get("odometer_reading"))
            price_val = sold_row.get("price_numeric")
            if price_val is None or pd.isna(price_val):
                price_val = parse_currency(sold_row.get("price"))
            if km_val is not None and price_val is not None and not pd.isna(km_val) and not pd.isna(price_val):
                sold_points.append((float(km_val), float(price_val)))

    lower_year, upper_year = _find_curve_year_bounds(curves_df, curve_tag, listing_year)
    if lower_year is not None and upper_year is not None and lower_year != upper_year:
        st.caption(f"Interpolated between {lower_year} and {upper_year} curves.")
        plotted = _render_interpolated_curve_plot(
            curves_df,
            curve_tag,
            listing_year or lower_year,
            parse_numeric(row.get("odometer_reading")),
            lower_year,
            upper_year,
            autotrader_points=autotrader_points if autotrader_points else None,
            sold_points=sold_points if sold_points else None,
        )
        if not plotted:
            st.info("Curve image not available for this tag.")
        return

    plot_year = listing_year
    if lower_year is not None and upper_year is not None and lower_year == upper_year:
        plot_year = lower_year

    if plot_year is not None:
        plotted = _render_single_curve_plot(
            curves_df,
            curve_tag,
            plot_year,
            parse_numeric(row.get("odometer_reading")),
            autotrader_points=autotrader_points if autotrader_points else None,
            sold_points=sold_points if sold_points else None,
        )
        if plotted:
            return

    image_name = _curve_image_filename(curve_tag)
    image_path = CURVE_IMAGE_DIR / image_name if image_name else None
    if image_path and image_path.exists():
        st.image(str(image_path), use_container_width=True)
    else:
        st.info("Curve image not available for this tag.")


def _render_autotrader_confirmation(row: pd.Series) -> None:
    st.markdown("**Autotrader check**")
    st.caption(
        "Confirms whether live and sold listings align with the curve estimate (confirmation only)."
    )

    resale_value = _compute_resale_value(row)
    if resale_value is None or pd.isna(resale_value):
        st.info("Curve estimate unavailable. Autotrader confirmation disabled.")
        return

    curve_tag = _curve_key_for_row(row)
    if not curve_tag:
        st.info("Curve tag missing. Autotrader confirmation disabled.")
        return

    matches, stats = _score_autotrader_matches(row, curve_tag, limit=50)
    make_label = _safe_text(row.get("make"), fallback="").strip() or "Make"
    if stats and stats.get("total"):
        st.caption(
            "Filter path: "
            f"{stats.get('total', 0)} total → "
            f"{stats.get('make_match', 0)} {make_label} → "
            f"{stats.get('group_match', 0)} group → "
            f"{stats.get('fuel_trans_body', 0)} fuel/trans/body → "
        f"{stats.get('km_window', 0)} within ±100,000 km"
        )
    year_note = ""
    listing_year = _safe_int(row.get("year"))
    if listing_year is not None and not matches.empty and "year" in matches.columns:
        year_matches = matches[pd.to_numeric(matches["year"], errors="coerce") == listing_year]
        if not year_matches.empty:
            matches = year_matches.reset_index(drop=True)
            year_note = f" (showing {listing_year} only)"

    st.caption(f"Debug: {len(matches)} Autotrader matches after filtering{year_note}.")
    if matches.empty:
        st.caption("No qualifying Autotrader matches found within the km window (±100,000 km).")
        return

    median_price = None
    if "price_value" in matches.columns:
        price_series = matches["price_value"].dropna()
        if not price_series.empty:
            median_price = float(price_series.median())
    diff_text = "N/A"
    delta_value = None
    if median_price is not None and resale_value:
        delta_value = (median_price - resale_value) / resale_value
        diff_text = f"{delta_value:+.1%}"

    match_count = len(matches)
    if match_count < 2 or delta_value is None:
        confidence_signal = "Conflicts"
    else:
        abs_delta = abs(delta_value)
        if abs_delta <= 0.05:
            confidence_signal = "Aligns"
        elif abs_delta <= 0.10:
            confidence_signal = "Mixed"
        else:
            confidence_signal = "Conflicts"

    st.caption(
        "Closest matches: "
        f"{match_count} | Median of matches: {_format_currency_value(median_price)} | "
        f"Delta vs curve: {diff_text} | Confidence: {confidence_signal}"
    )
    lifecycle = _market_lifecycle_summary(matches, resale_value)
    if lifecycle.get("near_curve_count"):
        median_days = lifecycle.get("median_days_listed")
        median_days_text = f"{float(median_days):.1f}" if median_days is not None else "N/A"
        st.caption(
            "Lifecycle signal: "
            f"{lifecycle.get('near_curve_count', 0)} near-curve match(es), "
            f"{lifecycle.get('fast_clear_count', 0)} cleared within 5 days, "
            f"{lifecycle.get('stale_active_count', 0)} active for 30+ days, "
            f"median days listed {median_days_text}."
        )

    display_cols = [
        "year",
        "model",
        "variant",
        "status",
        "price",
        "odometer",
        "location",
        "first_seen",
        "last_seen",
        "sold_date",
        "match_quality",
    ]
    table_df = matches[[col for col in display_cols if col in matches.columns]].copy()
    if "price" in table_df.columns:
        table_df["price"] = table_df["price"].apply(_format_price_text)
    if "odometer" in table_df.columns:
        table_df["odometer"] = table_df["odometer"].apply(_format_odometer)
    if "location" in table_df.columns:
        table_df["location"] = table_df["location"].apply(lambda val: extract_state(val) or _safe_text(val, ""))
    if "status" in table_df.columns:
        table_df["status"] = table_df["status"].apply(
            lambda val: "Sold" if str(val).strip().lower() == "sold" else "Live"
        )
    column_config = {}
    if "url" in matches.columns:
        table_df["link"] = matches["url"]
        ordered_cols = [col for col in display_cols if col in table_df.columns]
        if "link" not in ordered_cols:
            ordered_cols.append("link")
        table_df = table_df[ordered_cols]
        column_config["link"] = st.column_config.LinkColumn(
            "Link",
            display_text="Open",
        )
    st.dataframe(
        table_df,
        width="stretch",
        hide_index=True,
        column_config=column_config,
    )


def _get_curve_points_for_column(
    curves_df: pd.DataFrame,
    canonical_tag: str,
    anchor_year: int,
    price_column: str,
) -> list[tuple[int, int]]:
    if curves_df.empty or price_column not in curves_df.columns:
        return []
    curve_tag = resolve_curve_canonical_tag(canonical_tag)
    if not curve_tag:
        return []
    subset = curves_df[
        (curves_df["canonical_tag"] == curve_tag)
        & (curves_df["anchor_year"] == anchor_year)
    ].copy()
    subset = subset.dropna(subset=["km_bucket", price_column])
    if subset.empty:
        return []
    subset["km_bucket"] = pd.to_numeric(subset["km_bucket"], errors="coerce")
    subset[price_column] = pd.to_numeric(subset[price_column], errors="coerce")
    subset = subset.dropna(subset=["km_bucket", price_column]).sort_values("km_bucket")
    return [
        (int(km_bucket), int(price_value))
        for km_bucket, price_value in subset[["km_bucket", price_column]].itertuples(index=False, name=None)
    ]


def _interpolate_curve_value_by_year(
    curves_df: pd.DataFrame,
    canonical_tag: str,
    year: Optional[int],
    km: Optional[float],
    price_column: str,
) -> Optional[float]:
    if year is None or km is None:
        return None
    lower_year, upper_year = _find_curve_year_bounds(curves_df, canonical_tag, year)
    if lower_year is None or upper_year is None:
        return None

    lower_points = _get_curve_points_for_column(curves_df, canonical_tag, lower_year, price_column)
    upper_points = _get_curve_points_for_column(curves_df, canonical_tag, upper_year, price_column)
    if not lower_points and not upper_points:
        return None

    lower_value = interpolate_price_by_km(lower_points, km) if lower_points else None
    upper_value = interpolate_price_by_km(upper_points, km) if upper_points else None

    if lower_year == upper_year:
        return lower_value if lower_value is not None else upper_value
    if lower_value is None:
        return upper_value
    if upper_value is None:
        return lower_value

    ratio = (year - lower_year) / float(upper_year - lower_year)
    return lower_value + ratio * (upper_value - lower_value)


def _curve_range_for_row(row: pd.Series) -> tuple[Optional[float], Optional[float]]:
    curve_tag = _curve_key_for_row(row)
    if not curve_tag:
        return None, None
    year_value = _safe_int(row.get("year"))
    km_value = row.get("odometer_numeric")
    if km_value is None or (isinstance(km_value, float) and pd.isna(km_value)):
        km_value = parse_numeric(row.get("odometer_reading"))
    if km_value is None:
        return None, None

    low_value = _interpolate_curve_value_by_year(
        curves_df, curve_tag, year_value, float(km_value), "price_low"
    )
    high_value = _interpolate_curve_value_by_year(
        curves_df, curve_tag, year_value, float(km_value), "price_high"
    )
    return low_value, high_value


def _repair_deduction_value(row: pd.Series) -> int:
    assessment = _repair_assessment_for_row(row)
    return int(assessment.total_cost or 0)


def _repair_assessment_for_row(row: pd.Series):
    raw_notes = _safe_text(row.get("general_condition"), fallback="").strip()
    display_notes = _safe_text(row.get("normalized_condition_text"), fallback="").strip() or raw_notes
    adas_windscreen = bool(
        row.get("adas_windscreen") or row.get("windscreen_adas") or row.get("windshield_adas")
    )
    return assess_repairs(
        display_notes,
        adas_windscreen=adas_windscreen,
        vehicle_value=_resale_value_for_repairs(row),
        vehicle_class=vehicle_class_for_listing(row),
    )


def _format_repair_max_bid_deduction(row: pd.Series) -> str:
    assessment = _repair_assessment_for_row(row)
    if assessment.hard_avoid:
        return "Blocked"
    return _format_currency_value(assessment.total_cost_high or assessment.total_cost)


def _render_grays_comparables(row: pd.Series, comps_items: list[str]) -> None:
    _render_bullets("Auction sold comps (Grays)", comps_items)
    st.caption(
        "Auction sold comps support expected auction finish and bid risk. "
        "They do not set the Carsales resale curve."
    )
    tag_value = row.get("canonical_tag")
    if not tag_value or (isinstance(tag_value, float) and pd.isna(tag_value)):
        st.info("Vehicle curve tag missing. Historical Grays comparables unavailable.")
        return

    listing_year = _safe_int(row.get("year"))
    curve_key = resolve_curve_canonical_tag(tag_value)
    all_tag_comps = (
        sold_df[sold_df["curve_tag"] == curve_key]
        if "curve_tag" in sold_df.columns
        else sold_df[sold_df["canonical_tag"] == curve_key]
    )
    same_year_count = 0
    if listing_year is not None and "year_int" in all_tag_comps.columns:
        same_year_count = int((all_tag_comps["year_int"] == listing_year).sum())
    comps_df = _select_sold_subset(sold_df, tag_value, listing_year).copy()
    if comps_df.empty:
        st.info("No matching Grays sold comparables found for this listing.")
        return
    if listing_year is not None and same_year_count < 3:
        st.warning(
            f"Only {same_year_count} same-year Grays sold comp(s) for {listing_year}; "
            "showing nearby years from the same curve tag."
        )

    active_profile = build_defect_profile(row.to_dict())
    scores: list[int] = []
    qualities: list[str] = []
    defects: list[str] = []
    for _, comp_row in comps_df.iterrows():
        profile = build_defect_profile(comp_row.to_dict())
        score = similarity_score(active_profile, profile)
        scores.append(score)
        qualities.append(match_quality_from_score(score))
        defects.append(_defects_compact(profile))

    comps_df = comps_df.copy()
    comps_df["defect_match_score"] = scores
    comps_df["defect_match_quality"] = qualities
    comps_df["defects"] = defects
    comps_df["date_sold_parsed"] = pd.to_datetime(
        comps_df["date_sold"], errors="coerce"
    )
    comps_df = comps_df.sort_values(
        by=["defect_match_score", "date_sold_parsed"],
        ascending=[True, False],
        na_position="last",
    ).head(6)

    display_cols = [
        "year",
        "make",
        "model",
        "variant",
        "odometer_reading",
        "price",
        "date_sold",
        "defect_match_quality",
        "defects",
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

    comp_matrix = _build_grays_comparison_rows(row, comps_df)
    if not comp_matrix.empty:
        st.markdown("**Grays comparison (flags)**")
        headers = [
            "listing",
            "rego",
            "spare_key",
            "owners_manual",
            "service_history",
            "engine_starts",
            "cosmetic",
            "glass",
            "replacement",
            "structural",
            "mechanical",
            "interior",
            "repair_cost",
            "odometer",
            "price",
        ]
        column_map = {
            "rego": "rego_ok",
            "spare_key": "spare_key_ok",
            "owners_manual": "owners_manual_ok",
            "service_history": "service_history_ok",
            "engine_starts": "engine_turns_over_ok",
        }
        tip_map = {
            "rego": "tip_rego_ok",
            "spare_key": "tip_spare_key_ok",
            "owners_manual": "tip_owners_manual_ok",
            "service_history": "tip_service_history_ok",
            "engine_starts": "tip_engine_turns_over_ok",
            "cosmetic": "tip_cosmetic",
            "glass": "tip_glass",
            "replacement": "tip_replacement",
            "structural": "tip_structural",
            "mechanical": "tip_mechanical",
            "interior": "tip_interior",
            "repair_cost": "tip_repair_cost",
        }
        rows_html = []
        for _, matrix_row in comp_matrix.iterrows():
            cells = []
            for col in headers:
                source_col = column_map.get(col, col)
                val = matrix_row.get(source_col, "")
                tip_val = matrix_row.get(tip_map.get(col, ""), "")
                if col in (
                    "rego",
                    "spare_key",
                    "owners_manual",
                    "service_history",
                    "engine_starts",
                ):
                    cell = _bool_pill_html(val, tooltip=str(tip_val))
                elif col in (
                    "cosmetic",
                    "glass",
                    "replacement",
                    "structural",
                    "mechanical",
                    "interior",
                ):
                    sev = int(val) if str(val).isdigit() else 0
                    cell = _severity_pill_html(sev, tooltip=str(tip_val))
                elif col == "repair_cost":
                    cell = html.escape(_format_currency_value(parse_currency(val)))
                else:
                    text_val = str(val)
                    if col == "odometer":
                        text_val = text_val.replace(" km", "").replace("km", "").strip()
                    cell = html.escape(text_val)
                cells.append(f"<td>{cell}</td>")
            rows_html.append("<tr>" + "".join(cells) + "</tr>")

        header_html = "".join(
            f"<th>{html.escape(col).replace('_', '<br>')}</th>" for col in headers
        )
        table_html = (
            '<div class="autosniper-table" style="font-size: 0.85rem;">'
            "<table>"
            f"<thead><tr>{header_html}</tr></thead>"
            f"<tbody>{''.join(rows_html)}</tbody>"
            "</table>"
            "</div>"
        )
        st.markdown(table_html, unsafe_allow_html=True)

    unmatched = active_profile.get("unmatched_lines", [])
    if unmatched:
        display_notes = (
            _safe_text(row.get("normalized_condition_text"), fallback="").strip()
            or _safe_text(row.get("general_condition"), fallback="").strip()
        )
        appended = append_unclassified_condition_lines(
            unmatched,
            vehicle=_listing_title(row),
            url=_safe_text(row.get("url"), fallback=""),
            condition_notes=display_notes,
        )
        with st.expander("Unclassified condition lines", expanded=False):
            if appended:
                st.caption(f"Added {appended} item(s) to Repair Review.")
            st.markdown("\n".join(f"- {line}" for line in unmatched))

    comp_unmatched: list[str] = []
    for _, comp_row in comps_df.iterrows():
        comp_profile = build_defect_profile(comp_row.to_dict())
        comp_unmatched.extend(comp_profile.get("unmatched_lines", []))
    comp_unmatched = sorted({line for line in comp_unmatched if line})
    if comp_unmatched:
        with st.expander("Unclassified comp lines (Grays)", expanded=False):
            st.markdown("\n".join(f"- {line}" for line in comp_unmatched))


def _render_curve_tab(row: pd.Series) -> None:
    resale_display = _format_currency_value(_compute_resale_value(row))
    odometer_value = row.get("odometer_numeric")
    if odometer_value is None or (isinstance(odometer_value, float) and pd.isna(odometer_value)):
        odometer_value = row.get("odometer_reading")
    odometer_display = _format_odometer(odometer_value)
    curve_low, curve_high = _curve_range_for_row(row)
    range_display = (
        f"{_format_currency_value(curve_low)} - {_format_currency_value(curve_high)}"
        if curve_low is not None or curve_high is not None
        else "N/A"
    )

    metric_cols = st.columns(3)
    metric_cols[0].metric("Odometer anchor", odometer_display)
    metric_cols[1].metric("Resale estimate", resale_display)
    metric_cols[2].metric("Resale range", range_display)
    _render_curve_section(row)


def _render_comparables_tab(row: pd.Series, comps_items: list[str]) -> None:
    _render_autotrader_confirmation(row)
    st.divider()
    _render_grays_comparables(row, comps_items)


def _render_condition_tab(row: pd.Series, defect_profile: dict[str, object]) -> None:
    repair_deduction = _repair_deduction_value(row)
    max_bid_deduction = _format_repair_max_bid_deduction(row)
    metric_cols = st.columns(5)
    metric_cols[0].metric("Cosmetic damage", str(int(defect_profile.get("cosmetic", 0) or 0)))
    metric_cols[1].metric("Structural flags", str(int(defect_profile.get("structural", 0) or 0)))
    metric_cols[2].metric("Mechanical notes", str(int(defect_profile.get("mechanical", 0) or 0)))
    metric_cols[3].metric("Allowance", _format_currency_value(repair_deduction))
    metric_cols[4].metric("Bid deduction", max_bid_deduction)
    _render_condition_summary(row)


def _render_bid_logic_tab(
    row: pd.Series,
    *,
    risk_items: list[str],
) -> None:
    repair_deduction = _repair_deduction_value(row)
    max_bid_deduction = _format_repair_max_bid_deduction(row)
    auction_cost = _compute_auction_cost_value(row)
    confidence_value = row.get("confidence")
    confidence_percent = None
    if confidence_value is not None and not (isinstance(confidence_value, float) and pd.isna(confidence_value)):
        try:
            confidence_percent = float(confidence_value) * 100
        except (TypeError, ValueError):
            confidence_percent = None
    confidence_display = _format_percent(confidence_percent)
    if confidence_display == "N/A":
        confidence_display = _curve_confidence_label(row.get("confidence"))
    expected_finish_display, expected_finish_status = _expected_finish_display_parts(row)
    bid_display = bid_display_parts(row)
    cap_profit_display = _format_price_text(row.get("net_profit_worst") or row.get("net_profit_mid"))
    expected_profit_display = _format_price_text(row.get("expected_auction_worst_profit") or row.get("expected_auction_profit"))
    expected_profit_label = _display_profit_label(row.get("expected_auction_profit_label"))
    expected_finish_detail = f"Scenario profit {expected_profit_display}"
    if expected_profit_label not in ("Unknown", "N/A"):
        expected_finish_detail = f"{expected_finish_detail}; {expected_profit_label.lower()}"
    expected_finish_source = _safe_text(row.get("expected_auction_source"), "N/A")
    expected_finish_comps = _safe_text(row.get("expected_auction_comps_count"), "N/A")
    discount_display = (
        f"{float(row.get('discount_used') or 0):.0%}"
        if pd.notna(row.get("discount_used"))
        else "N/A"
    )
    difficulty_reasons = _safe_text(row.get("difficulty_reasons"), "N/A")

    metric_rows = [
        ("Resale estimate", _format_currency_value(_compute_resale_value(row))),
        ("Proxy max bid", bid_display["max_label"]),
        ("Worst profit at proxy max", cap_profit_display),
        ("Current vs proxy max", bid_display["status"]),
        ("Expected finish guide", expected_finish_display),
        ("Scenario profit at expected finish", expected_profit_display),
        ("Current price", _format_price_text(row.get("price"))),
        ("Auction cost", _format_currency_value(auction_cost)),
        ("Fees", _format_price_text(row.get("fees_estimate"))),
        ("Transport", _format_price_text(row.get("transport_estimate"))),
        ("Allowance", _format_currency_value(repair_deduction)),
        ("Bid deduction", max_bid_deduction),
        ("Confidence", confidence_display),
    ]

    first_row = st.columns(4)
    second_row = st.columns(4)
    third_row = st.columns(max(1, len(metric_rows) - 8))
    for column, (label, value) in zip(first_row, metric_rows[:4]):
        column.metric(label, value)
    for column, (label, value) in zip(second_row, metric_rows[4:8]):
        column.metric(label, value)
    for column, (label, value) in zip(third_row, metric_rows[8:]):
        column.metric(label, value)

    _render_bullets(
        "Bid decision",
        [
            f"Action: {_display_action_label(row.get('action_label'))}",
            f"{bid_display['status']}: {bid_display['status_detail']}",
            f"Expected finish: {expected_finish_display} ({expected_finish_detail}; {expected_finish_status})",
            f"Expected finish evidence: {expected_finish_source}; comps {expected_finish_comps}; discount {discount_display}",
            f"Costs included: fees {_format_price_text(row.get('fees_estimate'))}, transport {_format_price_text(row.get('transport_estimate'))}, repair/risk {_format_currency_value(repair_deduction)}",
            f"Flip difficulty: {_safe_text(row.get('flip_difficulty'), 'N/A')} - {difficulty_reasons}",
        ],
    )
    _render_bullets("Notes / risks", risk_items[:4])


def _build_grays_comparison_rows(listing_row: pd.Series, comps_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def _row_values(source_row: pd.Series) -> dict[str, object]:
        profile = build_defect_profile(source_row.to_dict())
        rego_no = _safe_text(source_row.get("rego_no"), fallback="").strip()
        rego_expiry = _safe_text(source_row.get("rego_expiry"), fallback="").strip()
        rego_tip_parts = []
        if rego_no:
            rego_tip_parts.append(f"rego_no: {rego_no}")
        if rego_expiry:
            rego_tip_parts.append(f"rego_expiry: {rego_expiry}")
        rego_tip = " | ".join(rego_tip_parts)
        def _bucket_tip(name: str) -> str:
            lines = profile.get("bucket_lines", {}).get(name, [])
            return " | ".join(lines) if lines else ""
        return {
            "rego_ok": _bool_label(profile["rego_ok"]),
            "spare_key_ok": _bool_label(profile["spare_key_ok"]),
            "owners_manual_ok": _bool_label(profile["owners_manual_ok"]),
            "service_history_ok": _bool_label(profile["service_history_ok"]),
            "engine_turns_over_ok": _bool_label(profile["engine_turns_over_ok"]),
            "cosmetic": int(profile["cosmetic"]),
            "glass": int(profile["glass"]),
            "replacement": int(profile["replacement"]),
            "structural": int(profile["structural"]),
            "mechanical": int(profile["mechanical"]),
            "interior": int(profile["interior"]),
            "tip_rego_ok": rego_tip,
            "tip_spare_key_ok": f"spare_key: {_safe_text(source_row.get('spare_key'), fallback='')}",
            "tip_owners_manual_ok": f"owners_manual: {_safe_text(source_row.get('owners_manual'), fallback='')}",
            "tip_service_history_ok": f"service_history: {_safe_text(source_row.get('service_history'), fallback='')}",
            "tip_engine_turns_over_ok": f"engine_turns_over: {_safe_text(source_row.get('engine_turns_over'), fallback='')}",
            "tip_cosmetic": _bucket_tip("cosmetic"),
            "tip_glass": _bucket_tip("glass"),
            "tip_replacement": _bucket_tip("replacement"),
            "tip_structural": _bucket_tip("structural"),
            "tip_mechanical": _bucket_tip("mechanical"),
            "tip_interior": _bucket_tip("interior"),
            "repair_cost": int(profile.get("repair_cost", 0) or 0),
            "tip_repair_cost": " | ".join(
                [
                    f"pills: {', '.join(profile.get('repair_pills', []) or [])}",
                    f"hard: {_safe_text(profile.get('repair_hard_avoid_reason'), fallback='none')}",
                    f"unclassified: {len(profile.get('unmatched_lines', []) or [])}",
                ]
            ),
        }

    listing_year = _safe_text(listing_row.get("year"), fallback="").strip()
    listing_label = f"{listing_year} (active)" if listing_year else "active"
    listing_flags = _row_values(listing_row)
    rows.append(
        {
            "listing": listing_label,
            **listing_flags,
            "odometer": _format_odometer(listing_row.get("odometer_reading")),
            "price": _format_price_text(listing_row.get("price")),
        }
    )

    for _, comp in comps_df.iterrows():
        comp_year = _safe_text(comp.get("year"), fallback="").strip()
        comp_label = comp_year if comp_year else "comp"
        comp_flags = _row_values(comp)
        rows.append(
            {
                "listing": comp_label,
                **comp_flags,
                "odometer": _format_odometer(comp.get("odometer_reading")),
                "price": _format_price_text(comp.get("price")),
            }
        )

    return pd.DataFrame(rows)


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
def load_external_active_data() -> pd.DataFrame:
    return _load_external_auction_active_rows()


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
    if "canonical_tag" in df.columns:
        df["canonical_tag"] = df["canonical_tag"].astype(str).str.strip()
    return df


@st.cache_data(ttl=300)
def load_sold_data() -> pd.DataFrame:
    sold_path = dataset_path("sold_cars_restricted.csv")
    df = pd.read_csv(sold_path)
    df, _ = validate_sold_cars_df(df)
    df["url"] = df["url"].astype(str).str.strip()
    df["odometer_numeric"] = df["odometer_reading"].apply(parse_numeric)
    df["price_numeric"] = df["price"].apply(parse_currency)
    return df


@st.cache_data(ttl=300)
def load_normalized_conditions() -> pd.DataFrame:
    path = Path("CSV_data/reports/normalized_conditions.csv")
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "component_normalized" not in df.columns or "url" not in df.columns:
        return pd.DataFrame()
    if "category_tags" in df.columns:
        tag_series = df["category_tags"].fillna("").astype(str).str.lower()
        df = df[~tag_series.str.contains(r"\bboilerplate\b", na=False)]
    df["url"] = df["url"].astype(str).str.strip()
    df["component_normalized"] = df["component_normalized"].astype(str).str.strip()
    df = df[df["component_normalized"] != ""]
    return df


def _select_sold_subset(
    sold_df: pd.DataFrame,
    canonical_tag: object,
    year_val: Optional[int],
    min_year_samples: int = 3,
) -> pd.DataFrame:
    if sold_df.empty or not canonical_tag:
        return pd.DataFrame()
    curve_key = resolve_curve_canonical_tag(canonical_tag)
    tag_column = "curve_tag" if "curve_tag" in sold_df.columns else "canonical_tag"
    subset = sold_df[sold_df[tag_column] == curve_key]
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


def _autotrader_cache_key() -> float | None:
    mtimes = []
    if AUTOTRADER_RECENT_MARKET.exists():
        mtimes.append(AUTOTRADER_RECENT_MARKET.stat().st_mtime)
    if AUTOTRADER_OUTPUT.exists():
        mtimes.append(AUTOTRADER_OUTPUT.stat().st_mtime)
    if AUTOTRADER_STATE.exists():
        mtimes.append(AUTOTRADER_STATE.stat().st_mtime)
    return max(mtimes) if mtimes else None


@st.cache_data(ttl=300)
def load_autotrader_data(raw_mtime: float | None = None) -> pd.DataFrame:
    if not AUTOTRADER_RECENT_MARKET.exists() and not AUTOTRADER_OUTPUT.exists() and not AUTOTRADER_STATE.exists():
        return pd.DataFrame()
    tagged_path = AUTOTRADER_OUTPUT.with_name(
        f"{AUTOTRADER_OUTPUT.stem}_tagged{AUTOTRADER_OUTPUT.suffix}"
    )
    raw_mtime = raw_mtime or _autotrader_cache_key()
    tagged_mtime = tagged_path.stat().st_mtime if tagged_path.exists() else None
    use_tagged = tagged_mtime is not None and tagged_mtime >= raw_mtime

    live_df = pd.DataFrame()
    if AUTOTRADER_RECENT_MARKET.exists():
        live_df = pd.read_csv(AUTOTRADER_RECENT_MARKET)
        live_df["source"] = live_df.get("source", "autotrader_recent_market")
        if AUTOTRADER_STATE.exists() and "url" in live_df.columns:
            state_df = pd.read_csv(AUTOTRADER_STATE)
            lifecycle_cols = [
                "url",
                "status",
                "first_seen",
                "last_seen",
                "last_price_date",
                "sold_date",
            ]
            state_cols = [col for col in lifecycle_cols if col in state_df.columns]
            if "url" in state_cols:
                live_df = live_df.merge(
                    state_df[state_cols].drop_duplicates("url", keep="last"),
                    on="url",
                    how="left",
                    suffixes=("", "_state"),
                )
                if "status_state" in live_df.columns:
                    if "status" not in live_df.columns:
                        live_df["status"] = ""
                    live_status = live_df["status"].fillna("").astype(str).str.strip()
                    live_df["status"] = live_df["status"].where(live_status.ne(""), live_df["status_state"])
                    live_df.drop(columns=["status_state"], inplace=True)
    elif AUTOTRADER_OUTPUT.exists():
        live_df = pd.read_csv(tagged_path if use_tagged else AUTOTRADER_OUTPUT)

    sold_df = pd.DataFrame()
    if live_df.empty and AUTOTRADER_STATE.exists():
        state_df = pd.read_csv(AUTOTRADER_STATE)
        if "status" in state_df.columns:
            sold_df = state_df[state_df["status"].str.lower() == "sold"].copy()
        else:
            sold_df = state_df.copy()
        if not sold_df.empty:
            sold_df["price"] = sold_df.get("last_price")
            sold_df["status"] = sold_df.get("status", "sold")
            sold_df["source"] = "autotrader_sold"

    df = pd.concat([frame for frame in (live_df, sold_df) if not frame.empty], ignore_index=True)
    if df.empty:
        return df
    for col in (
        "year",
        "make",
        "model",
        "variant",
        "body_type",
        "price",
        "odometer",
        "location",
        "transmission",
        "fuel_type",
        "rego",
        "url",
        "canonical_tag",
        "canonical_reason",
        "status",
        "source",
    ):
        if col not in df.columns:
            df[col] = ""
    df["make_norm"] = df["make"].apply(_normalize_match_text)
    df["model_norm"] = df["model"].apply(_normalize_match_text)
    df["variant_norm"] = df["variant"].apply(_normalize_match_text)
    df["transmission_norm"] = df["transmission"].apply(_normalize_match_text)
    df["fuel_norm"] = df["fuel_type"].apply(_normalize_match_text)
    df["body_norm"] = df["body_type"].apply(_normalize_match_text)
    df["year_int"] = df["year"].apply(_safe_int)
    df["price_value"] = df["price"].apply(parse_currency)
    df["odometer_value"] = df["odometer"].apply(parse_numeric)
    tag_series = df["canonical_tag"].fillna("").astype(str).str.strip()
    tag_series = tag_series.replace({"nan": "", "None": ""})
    needs_tagging = tag_series.eq("").any()
    if needs_tagging:
        tagged_df = tag_dataframe(
            df,
            source="autotrader",
            require_price=False,
            filter_unclassified=False,
            append_log=False,
        )
        filled = tag_series.ne("")
        df["canonical_tag"] = tagged_df["canonical_tag"].where(~filled, df["canonical_tag"])
        if "canonical_reason" in tagged_df.columns:
            reason_series = df["canonical_reason"].fillna("").astype(str).str.strip().replace({"nan": "", "None": ""})
            df["canonical_reason"] = tagged_df["canonical_reason"].where(reason_series.eq(""), df["canonical_reason"])
        tagged_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(tagged_path, index=False)
    allowed_tags = list_curve_tags(load_curves())
    if allowed_tags:
        df["canonical_tag"] = df["canonical_tag"].fillna("").astype(str).str.strip()
        df["canonical_tag"] = df["canonical_tag"].where(df["canonical_tag"].isin(allowed_tags), "UNCLASSIFIED")
        tagged_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(tagged_path, index=False)
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
    if df.empty or "canonical_tag" not in df.columns:
        return df
    corolla_mask = df["canonical_tag"].astype(str).str.lower().str.startswith("toyota_corolla")
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
autotrader_df = load_autotrader_data(_autotrader_cache_key())
normalized_conditions = load_normalized_conditions()
cached_results = load_cached_results()
cached_verdicts = {}
if not cached_results.empty and "url" in cached_results.columns:
    cached_verdicts = (
        cached_results[["url", "computed_verdict"]]
        .dropna(subset=["url"])
        .set_index("url")["computed_verdict"]
        .to_dict()
    )


active_groups = group_map_df[group_map_df["source"] == "active"][
    ["url", "canonical_tag", "reason_code"]
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

external_active_df = load_external_active_data()
if not external_active_df.empty:
    active_df = pd.concat([active_df, external_active_df], ignore_index=True, sort=False)
active_df = _exclude_shortlist_ineligible_rows(active_df)

if "time_remaining_or_date_sold" in active_df.columns:
    active_df["hours_remaining"] = active_df["time_remaining_or_date_sold"].apply(_extract_hours_remaining)
elif "date_sold" in active_df.columns:
    active_df["hours_remaining"] = active_df["date_sold"].apply(_extract_hours_remaining)
else:
    active_df["hours_remaining"] = None
if "odometer_reading" in active_df.columns:
    active_df["odometer_numeric"] = active_df["odometer_reading"].apply(parse_numeric)
if "price" in active_df.columns:
    active_df["price_numeric"] = active_df["price"].apply(parse_currency)

if not normalized_conditions.empty and "url" in active_df.columns:
    grouped = (
        normalized_conditions.groupby("url")["component_normalized"]
        .apply(lambda s: "\n".join(dict.fromkeys(s.tolist())))
        .to_dict()
    )
    active_df["normalized_condition_text"] = active_df["url"].map(grouped).fillna("")
    if "url" in sold_df.columns:
        sold_df["normalized_condition_text"] = sold_df["url"].map(grouped).fillna("")

sold_groups = group_map_df[group_map_df["source"] == "sold"][
    ["url", "canonical_tag", "reason_code"]
].rename(columns={"reason_code": "canonical_reason"})
sold_df = sold_df.merge(sold_groups, on="url", how="left")

allowed_tags: set[str] | None = set(
    curves_df.get("canonical_tag", pd.Series(dtype=str))
    .dropna()
    .astype(str)
    .str.strip()
    .tolist()
)
no_curve_active_df = pd.DataFrame()
if not allowed_tags:
    st.warning("curves.csv has no canonical tags; showing all tags.")
    allowed_tags = None
else:
    if "canonical_tag" not in active_df.columns:
        active_df["canonical_tag"] = ""
    active_df["canonical_tag"] = active_df["canonical_tag"].astype(str).str.strip()
    active_df["curve_tag"] = active_df["canonical_tag"].apply(resolve_curve_canonical_tag)
    active_df["tag_in_curves"] = active_df["curve_tag"].isin(allowed_tags)
    active_df["canonical_eligible"] = active_df.apply(
        lambda r: is_canonical_eligible(r.get("canonical_tag"), r.get("canonical_reason")),
        axis=1,
    )

    if "year" in active_df.columns and "anchor_year" in curves_df.columns:
        year_band = (
            curves_df.dropna(subset=["canonical_tag", "anchor_year"])
            .assign(anchor_year=lambda d: d["anchor_year"].apply(_safe_int))
            .dropna(subset=["anchor_year"])
            .groupby("canonical_tag")["anchor_year"]
            .agg(["min", "max"])
            .rename(columns={"min": "min_year", "max": "max_year"})
        )
        active_df = active_df.merge(year_band, left_on="curve_tag", right_index=True, how="left")
        active_df["year_int"] = active_df["year"].apply(_safe_int)
        active_df["year_in_range"] = (
            active_df["year_int"].notna()
            & active_df["min_year"].notna()
            & active_df["max_year"].notna()
            & (active_df["year_int"] >= active_df["min_year"])
            & (active_df["year_int"] <= active_df["max_year"])
        )
    else:
        active_df["year_in_range"] = False
    if "odometer_reading" in active_df.columns and "km_bucket" in curves_df.columns:
        km_band = (
            curves_df.dropna(subset=["canonical_tag", "km_bucket"])
            .assign(km_bucket=lambda d: d["km_bucket"].apply(_safe_int))
            .dropna(subset=["km_bucket"])
            .groupby("canonical_tag")["km_bucket"]
            .agg(["min", "max"])
            .rename(columns={"min": "min_km", "max": "max_km"})
        )
        active_df = active_df.merge(km_band, left_on="curve_tag", right_index=True, how="left")
        if "odometer_numeric" not in active_df.columns:
            active_df["odometer_numeric"] = active_df["odometer_reading"].apply(parse_numeric)
        active_df["km_in_range"] = active_df.apply(
            lambda row: km_within_curve_coverage(
                row.get("odometer_numeric"),
                row.get("min_km"),
                row.get("max_km"),
            ),
            axis=1,
        )
    else:
        active_df["km_in_range"] = False
    active_df["curve_coverage"] = (
        active_df["tag_in_curves"]
        & active_df["canonical_eligible"]
        & active_df["year_in_range"]
        & active_df["km_in_range"]
    )
    no_curve_active_df = active_df[~active_df["curve_coverage"]].copy()

    def _build_no_curve_reason(row: pd.Series) -> str:
        reasons = []
        if not row.get("tag_in_curves"):
            reasons.append("TAG_NOT_IN_CURVES")
        if not row.get("canonical_eligible"):
            reasons.append("NOT_ELIGIBLE")
        if not row.get("year_in_range"):
            reasons.append("YEAR_OUT_OF_RANGE")
        if not row.get("km_in_range"):
            reasons.append("KM_OUT_OF_RANGE")
        return ", ".join(reasons) if reasons else "NO_CURVE"

    no_curve_active_df["no_curve_reason"] = no_curve_active_df.apply(_build_no_curve_reason, axis=1)

    active_df = active_df[active_df["curve_coverage"]].copy()
    drop_cols = [
        "tag_in_curves",
        "canonical_eligible",
        "year_in_range",
        "km_in_range",
        "curve_coverage",
        "min_year",
        "max_year",
        "min_km",
        "max_km",
    ]
    active_df = active_df.drop(columns=[col for col in drop_cols if col in active_df.columns])
    no_curve_active_df = no_curve_active_df.drop(
        columns=[col for col in drop_cols if col in no_curve_active_df.columns]
    )

    if "canonical_tag" not in sold_df.columns:
        sold_df["canonical_tag"] = ""
    sold_df["canonical_tag"] = sold_df["canonical_tag"].astype(str).str.strip()
    sold_df["curve_tag"] = sold_df["canonical_tag"].apply(resolve_curve_canonical_tag)
    sold_df = sold_df[sold_df["curve_tag"].isin(allowed_tags)].copy()
sold_df = _exclude_corolla_sport_comps(sold_df)
sold_df = _exclude_major_engine_defects(sold_df)
sold_df = collapse_reauction_lifecycles(sold_df)
sold_df["year_int"] = sold_df["year"].apply(_safe_int) if "year" in sold_df.columns else None
if "curve_tag" not in sold_df.columns:
    sold_df["curve_tag"] = sold_df["canonical_tag"].apply(resolve_curve_canonical_tag)

curve_key_col = "curve_tag"

st.sidebar.header("Filters")
if allowed_tags:
    group_values = sorted({tag for tag in allowed_tags if tag and tag != UNCLASSIFIED})
else:
    group_values = sorted(
        {
            str(val).strip()
            for val in active_df.get("canonical_tag", pd.Series(dtype=str)).dropna().tolist()
            if str(val).strip() and str(val).strip() != UNCLASSIFIED
        }
    )
group_filter = st.sidebar.selectbox("Vehicle curve", ["All"] + group_values)
capital_lane_filter = st.sidebar.selectbox("Capital lane", CAPITAL_LANE_OPTIONS)
if capital_lane_filter == HIGHER_CAPITAL_LANE:
    st.sidebar.caption(
        "Curve resale $20k-$40k. Normal action, repair, risk and auction-site proxy ceilings still apply."
    )
refresh_clicked = st.sidebar.button("Refresh valuations")
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
            border-radius: 16px;
            padding: 1rem;
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
        ["Profit %", "Proxy max", "Auction ending soon"],
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
    hide_avoid = st.checkbox("Hide Avoid listings", value=True)
    hide_no_max_bid = st.checkbox("Hide listings without max bid", value=True)


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
            /* --sniper-card, --sniper-card-deep, --sniper-cyan-soft, --sniper-green,
               --sniper-amber, and --sniper-red used to be declared here too, but
               nothing in this file ever referenced them (verified via grep) --
               removed as dead custom properties. --sniper-cyan is kept as a local
               alias so the one real usage below doesn't need touching, but the
               actual color now lives once in shared/styling.py. */
            --sniper-cyan: var(--autosniper-signal-cyan);
        }
        .vehicle-card {
            --card-glow: 0 0 0 rgba(0, 0, 0, 0);
            --card-hover: 0 0 0 rgba(0, 0, 0, 0);
            background: linear-gradient(180deg, #08121d 0%, #0b0f14 30%, #0b0f14 100%);
            border: 1px solid rgba(39, 182, 255, 0.35);
            border-top: 3px solid var(--sniper-cyan);
            border-radius: 16px;
            padding: 0.9rem 1rem 0.85rem;
            margin-bottom: 0.8rem;
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
        [data-testid="stVerticalBlockBorderWrapper"]:has(.listing-shell-marker) {
            border-color: rgba(39, 182, 255, 0.32);
            border-radius: 18px;
            background: rgba(8, 18, 29, 0.34);
            padding: 0.35rem 0.85rem 0.8rem;
        }
        .listing-shell-marker {
            height: 0;
        }
        .listing-persistent-header {
            padding: 0.2rem 0.15rem 0.65rem;
        }
        .listing-spacer {
            height: 1.25rem;
        }
        [data-testid="stMetricValue"] {
            background: none !important;
            -webkit-background-clip: initial !important;
            -webkit-text-fill-color: #E5E5E5 !important;
            color: #E5E5E5 !important;
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
        .decision-signal-row {
            margin-top: 0.55rem;
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.5rem;
        }
        .decision-signal {
            min-height: 62px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.14);
            background: rgba(255, 255, 255, 0.045);
            padding: 0.48rem 0.58rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .decision-signal-label {
            font-size: 0.55rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: rgba(255, 255, 255, 0.52);
            margin-bottom: 0.16rem;
        }
        .decision-signal-value {
            font-size: 0.98rem;
            font-weight: 850;
            line-height: 1.05;
            color: rgba(255, 255, 255, 0.94);
        }
        .decision-signal-sub {
            margin-top: 0.18rem;
            font-size: 0.6rem;
            line-height: 1.2;
            color: rgba(255, 255, 255, 0.58);
        }
        .decision-signal.signal-good {
            border-color: rgba(44, 255, 154, 0.55);
            background: rgba(44, 255, 154, 0.1);
        }
        .decision-signal.signal-good .decision-signal-value {
            color: #dcffef;
        }
        .decision-signal.signal-watch {
            border-color: rgba(255, 179, 71, 0.6);
            background: rgba(255, 179, 71, 0.1);
        }
        .decision-signal.signal-watch .decision-signal-value {
            color: #fff1d8;
        }
        .decision-signal.signal-danger {
            border-color: rgba(255, 77, 77, 0.65);
            background: rgba(255, 77, 77, 0.11);
        }
        .decision-signal.signal-danger .decision-signal-value {
            color: #ffe3e3;
        }
        .decision-signal.signal-neutral {
            border-color: rgba(39, 182, 255, 0.25);
            background: rgba(39, 182, 255, 0.06);
        }
        /* .card-actions a / a:hover now live in shared/styling.py so this
           page and 8_MISSED_OPPORTUNITIES.py share one definition. */
        .card-metrics {
            margin-top: 0.5rem;
            display: grid;
            grid-template-columns: minmax(220px, 1fr) minmax(260px, 1.35fr) minmax(220px, 1fr);
            gap: 0.65rem;
            align-items: stretch;
        }
        .metric-group {
            border-radius: 12px;
            padding: 0.62rem 0.72rem 0.68rem;
            background: rgba(8, 12, 18, 0.72);
            border: 1px solid rgba(39, 182, 255, 0.22);
            border-left: 3px solid rgba(39, 182, 255, 0.65);
            min-height: 126px;
        }
        .metric-group.money-group {
            border-left-color: rgba(44, 255, 154, 0.72);
        }
        .metric-group.context-group {
            border-left-color: rgba(255, 179, 71, 0.68);
        }
        .metric-group-title {
            margin-bottom: 0.46rem;
            font-size: 0.58rem;
            line-height: 1;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            color: rgba(255, 255, 255, 0.58);
        }
        .metric-group-items {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.46rem 0.62rem;
        }
        .metric-group.auction-group .metric-group-items,
        .metric-group.context-group .metric-group-items {
            grid-template-columns: 1fr;
        }
        .metric-item {
            min-width: 0;
            padding-top: 0.36rem;
            border-top: 1px solid rgba(255, 255, 255, 0.08);
        }
        .metric-item.primary {
            padding: 0.36rem 0.44rem 0.42rem;
            border: 1px solid rgba(39, 182, 255, 0.34);
            border-radius: 8px;
            background: rgba(39, 182, 255, 0.07);
        }
        .metric-item.price-up {
            border-color: rgba(44, 255, 154, 0.5);
            background: rgba(44, 255, 154, 0.08);
        }
        .metric-item.price-down {
            border-color: rgba(255, 179, 71, 0.52);
            background: rgba(255, 179, 71, 0.08);
        }
        .metric-item.price-flat {
            border-color: rgba(255, 255, 255, 0.1);
            background: rgba(255, 255, 255, 0.035);
        }
        .metric-box {
            background: rgba(8, 12, 18, 0.65);
            border: 1px solid rgba(39, 182, 255, 0.3);
            border-radius: 12px;
            padding: 0.55rem 0.7rem;
            min-height: 56px;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .metric-label {
            font-size: 0.58rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: var(--autosniper-muted);
            margin-bottom: 0.14rem;
        }
        .metric-value {
            font-size: 1rem;
            font-weight: 800;
            color: var(--autosniper-primary);
            line-height: 1.05;
        }
        .metric-item.primary .metric-value {
            font-size: 1.16rem;
        }
        .metric-box.primary .metric-value {
            font-size: 1.18rem;
        }
        .metric-box.price-up {
            border-color: rgba(44, 255, 154, 0.8);
            background: rgba(44, 255, 154, 0.1);
        }
        .metric-box.price-up .metric-value {
            color: #2cff9a;
        }
        .metric-box.price-down {
            border-color: rgba(255, 179, 71, 0.75);
            background: rgba(255, 179, 71, 0.1);
        }
        .metric-box.price-down .metric-value {
            color: #ffb347;
        }
        .metric-box.price-flat {
            border-color: rgba(255, 255, 255, 0.14);
            background: rgba(255, 255, 255, 0.04);
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
        .action-pill {
            background: rgba(39, 182, 255, 0.14);
            border-color: rgba(39, 182, 255, 0.85);
            color: #e4f7ff;
            box-shadow: 0 0 12px rgba(39, 182, 255, 0.28);
        }
        .support-pill {
            opacity: 0.82;
            font-size: 0.58rem;
            padding: 0.25rem 0.55rem;
        }
        .support-pill.context-pill {
            opacity: 0.68;
            box-shadow: none;
        }
        .chip-row {
            margin-top: 0.3rem;
            display: flex;
            flex-wrap: wrap;
            gap: 0.3rem;
        }
        .confidence-badge-row {
            margin-top: 0.55rem;
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
        }
        .confidence-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.32rem 0.58rem;
            border-radius: 999px;
            border: 1px solid rgba(39, 182, 255, 0.28);
            background: rgba(11, 15, 20, 0.72);
            font-size: 0.62rem;
        }
        .confidence-badge-label {
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: rgba(255, 255, 255, 0.6);
        }
        .confidence-badge-value {
            font-weight: 800;
            letter-spacing: 0.08em;
            color: rgba(255, 255, 255, 0.92);
        }
        .confidence-badge.badge-high {
            border-color: rgba(44, 255, 154, 0.5);
            background: rgba(44, 255, 154, 0.1);
        }
        .confidence-badge.badge-medium {
            border-color: rgba(255, 179, 71, 0.55);
            background: rgba(255, 179, 71, 0.1);
        }
        .confidence-badge.badge-low {
            border-color: rgba(255, 77, 77, 0.55);
            background: rgba(255, 77, 77, 0.1);
        }
        .confidence-badge.badge-neutral {
            border-color: rgba(39, 182, 255, 0.28);
            background: rgba(39, 182, 255, 0.08);
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
                grid-template-columns: 1fr;
            }
            .decision-signal-row {
                grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            }
            .metric-group.money-group .metric-group-items {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

filtered = active_df.copy()
if linked_listing_mode and "url" in filtered.columns:
    filtered = filtered[filtered["url"].astype(str).str.strip() == target_listing_url].copy()
else:
    if "hours_remaining" in filtered.columns and (min_hours is not None or max_hours is not None):
        filtered = filtered[filtered["hours_remaining"].notna()]
        if min_hours is not None:
            filtered = filtered[filtered["hours_remaining"] >= min_hours]
        if max_hours is not None:
            filtered = filtered[filtered["hours_remaining"] < max_hours]

    if group_filter != "All":
        group_column = "curve_tag" if "curve_tag" in filtered.columns else "canonical_tag"
        filtered = filtered[filtered[group_column] == group_filter]

if "canonical_tag" not in filtered.columns:
    filtered["canonical_tag"] = ""
filtered["canonical_tag"] = filtered["canonical_tag"].astype(str).str.strip()
filtered = filtered[filtered["canonical_tag"] != ""].copy()
if allowed_tags:
    if "curve_tag" not in filtered.columns:
        filtered["curve_tag"] = filtered["canonical_tag"].apply(resolve_curve_canonical_tag)
    filtered = filtered[filtered["curve_tag"].isin(allowed_tags)].copy()

no_curve_filtered = no_curve_active_df.copy()
if not no_curve_filtered.empty:
    if linked_listing_mode and "url" in no_curve_filtered.columns:
        no_curve_filtered = no_curve_filtered[
            no_curve_filtered["url"].astype(str).str.strip() == target_listing_url
        ].copy()
    else:
        if "hours_remaining" in no_curve_filtered.columns and (min_hours is not None or max_hours is not None):
            no_curve_filtered = no_curve_filtered[no_curve_filtered["hours_remaining"].notna()]
            if min_hours is not None:
                no_curve_filtered = no_curve_filtered[no_curve_filtered["hours_remaining"] >= min_hours]
            if max_hours is not None:
                no_curve_filtered = no_curve_filtered[no_curve_filtered["hours_remaining"] < max_hours]
        if group_filter != "All":
            group_column = "curve_tag" if "curve_tag" in no_curve_filtered.columns else "canonical_tag"
            if group_column in no_curve_filtered.columns:
                no_curve_filtered = no_curve_filtered[no_curve_filtered[group_column] == group_filter]

def _render_no_curve_section(no_curve_df: pd.DataFrame) -> None:
    if no_curve_df.empty:
        return
    no_curve_html = clean_html(
        f"""
        <div class="autosniper-section">
            <div class="section-title">Diagnostics</div>
            <div class="section-subtitle">
                {len(no_curve_df):,} active listing(s) do not currently have enough curve coverage for AI pricing.
            </div>
        </div>
        """
    )
    st.markdown(no_curve_html, unsafe_allow_html=True)
    with st.expander("View no-curve diagnostics", expanded=False):
        display_cols = [
            "year",
            "make",
            "model",
            "variant",
            "odometer_reading",
            "price",
            "location",
            "no_curve_reason",
            "url",
        ]
        available_cols = [col for col in display_cols if col in no_curve_df.columns]
        if available_cols:
            st.dataframe(
                no_curve_df[available_cols],
                use_container_width=True,
                hide_index=True,
            )

if filtered.empty:
    if linked_listing_mode:
        linked_summary_html = clean_html(
            """
            <div class="autosniper-section">
                <div class="section-title">Linked AI Analysis</div>
                <div class="section-subtitle">Showing this vehicle only from the Telegram alert link.</div>
            </div>
            """
        )
        st.markdown(linked_summary_html, unsafe_allow_html=True)

    if linked_listing_mode and no_curve_filtered.empty:
        st.warning("The linked listing is not in the current AI Analysis active set.")
    elif linked_listing_mode:
        st.info("The linked listing is active, but it does not currently have enough curve coverage for AI pricing.")
        _render_no_curve_section(no_curve_filtered)
    elif no_curve_filtered.empty:
        st.info("No active listings match the current filters.")
    else:
        st.info("No curve-covered listings match the current filters.")
        _render_no_curve_section(no_curve_filtered)
    st.stop()


results: list[Dict[str, Any]] = []
for _, row in filtered.iterrows():
    canonical_tag = _safe_text(row.get("canonical_tag"), fallback="").strip()
    canonical_reason = _safe_text(row.get("canonical_reason"), fallback="").strip()
    year_val = _safe_int(row.get("year"))
    odo_val = row.get("odometer_numeric")
    spec_reason = ""
    if not is_canonical_eligible(canonical_tag, canonical_reason):
        continue

    curve_key = resolve_curve_canonical_tag(canonical_tag)
    curve_subset = curves_df[curves_df["canonical_tag"] == curve_key] if curve_key else pd.DataFrame()
    if curve_subset.empty:
        spec_reason = "NO_CURVE"

    base_estimate = None
    if not spec_reason:
        base_estimate = interpolate_base_by_year(curves_df, curve_key, year_val, odo_val)
    trim_multiplier = None
    adjusted_estimate = base_estimate
    sold_subset = _select_sold_subset(sold_df, curve_key, year_val)
    sold_subset, comp_stats = select_km_aware_comparables(sold_subset, odo_val)
    comps_count = comp_stats.count
    comps_median = comp_stats.median
    comps_mean = comp_stats.mean
    comps_min = comp_stats.minimum
    comps_max = comp_stats.maximum
    expected_sale, expected_sale_note = _estimate_expected_sale(
        adjusted_estimate,
        comps_median,
        comps_count,
    )

    km_percentile = None
    historical_matches = []
    if not sold_subset.empty:
        km_percentile = _km_percentile(sold_subset["odometer_numeric"], odo_val)
        historical_matches = _build_historical_matches(sold_subset["odometer_numeric"])

    autotrader_median = None
    listings_cluster_ok = False
    market_lifecycle = None
    curve_tag = _curve_key_for_row(row)
    at_matches, _ = _score_autotrader_matches(row, curve_tag, limit=50)
    if not at_matches.empty and "price_value" in at_matches.columns:
        price_series = at_matches["price_value"].dropna()
        if not price_series.empty:
            autotrader_median = float(price_series.median())
    market_lifecycle = _market_lifecycle_summary(at_matches, adjusted_estimate)
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
                "comps_count": comps_count,
                "comps_median": comps_median,
                "comps_mean": comps_mean,
                "comps_min": comps_min,
                "comps_max": comps_max,
                "comps_method": comp_stats.method,
                "comps_km_min": comp_stats.km_min,
                "comps_km_max": comp_stats.km_max,
                "comps_km_distance_median": comp_stats.km_distance_median,
                "expected_sale": expected_sale,
                "expected_sale_note": expected_sale_note or "No curve / Not eligible",
            }
        )
        continue

    url_value = row.get("url")
    cached_verdict = _safe_text(cached_verdicts.get(url_value), fallback="")
    force_refresh_row = force_refresh or (
        cached_verdict and "not eligible" in cached_verdict.lower()
    )
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
        market_lifecycle=market_lifecycle,
        reauction_context=reauction_context_for_listing(row, sold_df),
        force_refresh=force_refresh_row,
    )
    analysis["curve_base"] = base_estimate
    analysis["curve_adjusted"] = adjusted_estimate
    analysis["trim_multiplier"] = trim_multiplier
    analysis["comps_count"] = comps_count
    analysis["comps_median"] = comps_median
    analysis["comps_mean"] = comps_mean
    analysis["comps_min"] = comps_min
    analysis["comps_max"] = comps_max
    analysis["comps_method"] = comp_stats.method
    analysis["comps_km_min"] = comp_stats.km_min
    analysis["comps_km_max"] = comp_stats.km_max
    analysis["comps_km_distance_median"] = comp_stats.km_distance_median
    analysis["expected_sale"] = expected_sale
    analysis["expected_sale_note"] = expected_sale_note
    analysis["spec_reason"] = spec_reason or ""
    results.append(analysis)


results_df = pd.DataFrame(results)
output = filtered.merge(results_df, on="url", how="left")


def _coalesce_merged_display_column(df: pd.DataFrame, column: str) -> None:
    left_column = f"{column}_x"
    right_column = f"{column}_y"
    if left_column not in df.columns and right_column not in df.columns:
        return

    if column in df.columns:
        series = df[column]
    elif left_column in df.columns:
        series = df[left_column]
    else:
        series = pd.Series([None] * len(df), index=df.index)

    if right_column in df.columns:
        text_series = series.astype(str).str.strip().str.lower()
        missing_mask = series.isna() | text_series.isin(["", "nan", "none", "n/a"])
        series = series.where(~missing_mask, df[right_column])

    df[column] = series
    df.drop(columns=[col for col in (left_column, right_column) if col in df.columns], inplace=True)


for display_column in ("year", "make", "model", "variant", "location"):
    _coalesce_merged_display_column(output, display_column)


def _compute_profit_margin_value(row: pd.Series) -> Optional[float]:
    margin_value = conservative_margin_percent(row)
    if margin_value is not None:
        return margin_value
    net_profit = first_currency_value(row.get("net_profit_worst"), row.get("net_profit_mid"))
    resale = first_currency_value(
        row.get("resale_mid"),
        row.get("expected_sale"),
        row.get("curve_adjusted"),
    )
    if net_profit is not None and resale:
        return (net_profit / resale) * 100
    return None


def _compute_resale_value(row: pd.Series) -> Optional[float]:
    return first_currency_value(
        row.get("expected_sale"),
        row.get("resale_mid"),
        row.get("curve_adjusted"),
    )


def _compute_max_bid_value(row: pd.Series) -> Optional[float]:
    return recommended_max_bid_value(row)


def _compute_auction_cost_value(row: pd.Series) -> Optional[float]:
    values = [
        parse_currency(row.get("fees_estimate")),
        parse_currency(row.get("transport_estimate")),
        parse_currency(row.get("rego_estimate")),
        parse_currency(row.get("roadworthy_estimate")),
        parse_currency(row.get("prep_estimate")),
        parse_currency(row.get("repair_estimate")),
    ]
    if all(value is None for value in values):
        return None
    return float(sum(value or 0.0 for value in values))


def _compute_score_100_value(row: pd.Series) -> Optional[float]:
    score_10 = row.get("score_out_of_10")
    if score_10 is not None and not (isinstance(score_10, float) and pd.isna(score_10)):
        try:
            value = float(score_10)
            if 0 <= value <= 10:
                return round(value * 10, 1)
        except (TypeError, ValueError):
            pass

    confidence = row.get("confidence")
    if confidence is None or (isinstance(confidence, float) and pd.isna(confidence)):
        return None
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return None
    if 0 <= value <= 1:
        return round(value * 100, 1)
    if 1 < value <= 100:
        return round(value, 1)
    return None


def _split_notes(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    return [note.strip() for note in text.split(";") if note.strip()]


def _truthy(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1"}:
        return True
    return False


def _resolve_action_label(row: pd.Series) -> str:
    current_action = _safe_text(row.get("action_label"), fallback="Review")
    return derive_action_label_from_row(
        row,
        min_profit=MIN_NET_PROFIT_ABSOLUTE,
        fallback=current_action,
    )


output = output.copy()
output["action_label"] = output.apply(_resolve_action_label, axis=1)
output["profit_margin_value"] = output.apply(_compute_profit_margin_value, axis=1)
output["resale_value"] = output.apply(_compute_resale_value, axis=1)
output["capital_lane"] = output["resale_value"].apply(classify_capital_lane)
output["max_bid_value"] = output.apply(_compute_max_bid_value, axis=1)
output["score_100_value"] = output.apply(_compute_score_100_value, axis=1)
output["verdict_label"] = output["computed_verdict"].apply(lambda value: _map_verdict_label(str(value))[0])
output["verdict_class"] = output["computed_verdict"].apply(lambda value: _map_verdict_label(str(value))[1])

filtered_output = output.copy()
if target_listing_url and "url" in filtered_output.columns:
    filtered_output = filtered_output[filtered_output["url"].astype(str).str.strip() == target_listing_url].copy()
    if filtered_output.empty:
        st.warning("The linked listing is not in the current AI Analysis active set.")
else:
    filtered_output = apply_global_sidebar_filters(
        filtered_output,
        state_columns=("location_state", "rego_state", "location"),
        vehicle_type_columns=("body_type", "body"),
        margin_columns=("profit_margin_value", "profit_margin_percent"),
        canonical_tag_column="curve_tag",
        curve_tags=allowed_tags,
    )
    if group_filter != "All":
        group_column = "curve_tag" if "curve_tag" in filtered_output.columns else "canonical_tag"
        filtered_output = filtered_output[filtered_output[group_column] == group_filter]

    if capital_lane_filter != ALL_CAPITAL_LANES:
        filtered_output = filter_capital_lane(filtered_output, capital_lane_filter)

    if hide_avoid:
        filtered_output = filtered_output[filtered_output["action_label"] != "Avoid"]

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
elif sort_choice == "Proxy max":
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

if "url" in filtered_output.columns:
    filtered_output = filtered_output.drop_duplicates(subset=["url"], keep="first")

hidden_count = max(0, len(output) - len(filtered_output))
active_filter_labels = []
if hide_avoid:
    active_filter_labels.append("Avoid listings hidden")
if hide_no_max_bid:
    active_filter_labels.append("no-max-bid listings hidden")
if min_margin > 0:
    active_filter_labels.append(f"minimum margin {min_margin:.0f}%")
if time_bucket != "All":
    active_filter_labels.append(f"time bucket {time_bucket}")
if group_filter != "All":
    active_filter_labels.append("vehicle curve selected")
active_filter_text = "; ".join(active_filter_labels) if active_filter_labels else "No extra filters active"
if linked_listing_mode:
    summary_title = "Linked AI Analysis"
    summary_subtitle = "Showing this vehicle only from the Telegram alert link."
else:
    summary_title = "Active AI Opportunities"
    summary_subtitle = (
        f"Showing {len(filtered_output):,} of {len(output):,} curve-covered listing(s). "
        f"{hidden_count:,} hidden by current filters. {active_filter_text}."
    )

summary_html = clean_html(
    f"""
    <div class="autosniper-section">
        <div class="section-title">{summary_title}</div>
        <div class="section-subtitle">{summary_subtitle}</div>
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


def _build_metric_item(label: str, value: str, subtext: Optional[str] = None, class_name: Optional[str] = None) -> str:
    sub_html = f'<div class="metric-sub">{html.escape(subtext)}</div>' if subtext else ""
    class_attr = f"metric-item {class_name}".strip() if class_name else "metric-item"
    return "".join(
        [
            f'<div class="{class_attr}">',
            f'<div class="metric-label">{html.escape(label)}</div>',
            f'<div class="metric-value">{html.escape(value)}</div>',
            sub_html,
            "</div>",
        ]
    )


def _build_metric_group(title: str, items: list[str], class_name: str) -> str:
    return "".join(
        [
            f'<div class="metric-group {html.escape(class_name)}">',
            f'<div class="metric-group-title">{html.escape(title)}</div>',
            '<div class="metric-group-items">',
            "".join(items),
            "</div>",
            "</div>",
        ]
    )


def _format_age_minutes(minutes: float) -> str:
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{int(round(minutes))}m ago"
    hours = minutes / 60.0
    if hours < 24:
        return f"{hours:.1f}h ago"
    days = hours / 24.0
    return f"{days:.1f}d ago"


def _price_update_box(row: pd.Series) -> tuple[str, str, str]:
    direction = _safe_text(row.get("price_change_direction"), fallback="").strip().lower()
    changed_at = pd.to_datetime(row.get("price_changed_at"), errors="coerce", utc=True)
    if pd.isna(changed_at):
        return "No increase", "No recent price increase logged", "price-flat"

    now = pd.Timestamp.now(tz="UTC")
    age_minutes = max(0.0, (now - changed_at).total_seconds() / 60.0)
    delta_value = parse_currency(row.get("price_change_delta"))
    delta_display = _format_currency_value(abs(delta_value)) if delta_value is not None else "N/A"
    previous_display = _format_price_text(row.get("previous_current_bid"))
    age_display = _format_age_minutes(age_minutes)

    if direction == "increased" and age_minutes <= 60:
        return "Up last hour", f"+{delta_display} from {previous_display} ({age_display})", "price-up"
    if direction == "decreased" and age_minutes <= 60:
        return "Down last hour", f"-{delta_display} from {previous_display} ({age_display})", "price-down"
    if direction == "increased":
        return "No increase", f"Last up +{delta_display} {age_display}", "price-flat"
    if direction == "decreased":
        return "No increase", f"Last down -{delta_display} {age_display}", "price-flat"
    return "No increase", f"Last price change {age_display}", "price-flat"


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


def _data_completeness_label(row: pd.Series) -> str:
    checks = [
        bool(_safe_text(row.get("canonical_tag"), fallback="").strip()),
        bool(_safe_text(row.get("normalized_condition_text"), fallback="").strip()),
        parse_numeric(row.get("odometer_reading")) is not None,
        parse_currency(row.get("price")) is not None,
        bool(_curve_key_for_row(row)),
    ]
    score = sum(1 for check in checks if check)
    if score >= 5:
        return "High"
    if score >= 3:
        return "Medium"
    return "Low"


def _risk_level_label(row: pd.Series, combined_flags: list[str], defect_profile: dict[str, object]) -> str:
    if int(defect_profile.get("mechanical", 0) or 0) >= 1 or int(defect_profile.get("structural", 0) or 0) >= 1:
        return "High"
    if len(combined_flags) >= 4:
        return "High"
    if len(combined_flags) >= 2 or int(defect_profile.get("replacement", 0) or 0) >= 1:
        return "Medium"
    return "Low"


def _badge_tone(value: str) -> str:
    normalized = _safe_text(value, fallback="").strip().lower()
    if normalized == "high":
        return "badge-high"
    if normalized == "medium":
        return "badge-medium"
    if normalized == "low":
        return "badge-low"
    return "badge-neutral"


def _confidence_badges_html(curve_confidence: str, data_completeness: str, risk_level: str) -> str:
    badge_values = [
        ("Curve Confidence", curve_confidence),
        ("Data Completeness", data_completeness),
        ("Risk Level", risk_level),
    ]
    badges = []
    for label, value in badge_values:
        badges.append(
            "".join(
                [
                    f'<div class="confidence-badge {_badge_tone(value)}">',
                    f'<span class="confidence-badge-label">{html.escape(label)}</span>',
                    f'<span class="confidence-badge-value">{html.escape(value.upper())}</span>',
                    "</div>",
                ]
            )
        )
    return f'<div class="confidence-badge-row">{"".join(badges)}</div>'


def _signal_tone(value: object) -> str:
    normalized = _safe_text(value, fallback="").strip().lower()
    if any(
        token in normalized
        for token in ["avoid", "over max", "no edge", "trap", "low", "high risk", "policy blocked", "no policy bid"]
    ):
        return "signal-danger"
    if any(token in normalized for token in ["watch", "review", "marginal", "conditional", "medium", "unknown"]):
        return "signal-watch"
    if any(token in normalized for token in ["buy", "cheap", "strong", "good", "high", "safe"]):
        return "signal-good"
    return "signal-neutral"


def _risk_signal_tone(value: object) -> str:
    normalized = _safe_text(value, fallback="").strip().lower()
    if normalized == "high":
        return "signal-danger"
    if normalized == "medium":
        return "signal-watch"
    if normalized == "low":
        return "signal-good"
    return "signal-neutral"


def _margin_signal_tone(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "signal-neutral"
    if numeric >= 25:
        return "signal-good"
    if numeric >= 10:
        return "signal-watch"
    return "signal-danger"


def _build_signal_tile(label: str, value: str, sub: str, tone: str) -> str:
    return "".join(
        [
            f'<div class="decision-signal {html.escape(tone)}">',
            f'<div class="decision-signal-label">{html.escape(label)}</div>',
            f'<div class="decision-signal-value">{html.escape(value)}</div>',
            f'<div class="decision-signal-sub">{html.escape(sub)}</div>' if sub else "",
            "</div>",
        ]
    )


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
    action_label = _display_action_label(row.get("action_label"))

    bid_display = bid_display_parts(row)
    max_bid_display = bid_display["max_label"]
    resale_display = _format_currency_value(row.get("resale_value"))
    profit_pct_display = _format_percent(row.get("profit_margin_value"))
    expected_auction_display, expected_finish_status = _expected_finish_display_parts(row)
    expected_profit_display = _format_price_text(row.get("expected_auction_worst_profit") or row.get("expected_auction_profit"))
    expected_profit_label = _display_profit_label(row.get("expected_auction_profit_label"))
    hard_max_safety = _max_bid_safety_text(row)
    cap_profit_display = _format_price_text(row.get("net_profit_worst") or row.get("net_profit_mid"))
    expected_finish_sub = f"{expected_finish_status}; scenario profit {expected_profit_display}"
    if expected_profit_label not in ("Unknown", "N/A"):
        expected_finish_sub = f"{expected_finish_sub}; {expected_profit_label.lower()}"
    flip_difficulty = _safe_text(row.get("flip_difficulty"), fallback="Unknown")
    bid_status = bid_display["status"]
    score_100 = row.get("score_100_value")
    score_100_display = "N/A"
    if score_100 is not None and not (isinstance(score_100, float) and pd.isna(score_100)):
        try:
            score_100_display = f"{float(score_100):.0f}"
        except (TypeError, ValueError):
            score_100_display = "N/A"

    current_price_display = _format_price_text(row.get("price"))
    price_update_value, price_update_sub, price_update_class = _price_update_box(row)
    raw_time_value = row.get("time_remaining_or_date_sold") or row.get("date_sold")
    time_left_display = _format_time_remaining(row.get("hours_remaining"), raw_time_value)

    rego_text = _format_rego(row.get("rego_expiry"), row.get("rego_no"))
    rego_status = _rego_status(row.get("rego_expiry"), row.get("rego_no"))
    location_state = extract_state(
        row.get("location_state") or row.get("rego_state") or row.get("location")
    )
    risk_flags = _parse_risk_flags(row.get("risk_flags"))
    condition_flags = _detect_condition_flags(_get_condition_text(row))
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

    header_meta_parts = []
    capital_lane = _safe_text(row.get("capital_lane"), fallback="").strip()
    if capital_lane:
        header_meta_parts.append(capital_lane)
    if canonical_tag:
        header_meta_parts.append(f"Tag {canonical_tag}")
    normalized_text = _safe_text(row.get("normalized_condition_text"), fallback="").strip()
    if normalized_text:
        header_meta_parts.append("Normalized: Yes")
    else:
        header_meta_parts.append("Normalized: No")
    header_meta = " | ".join(header_meta_parts)

    defect_profile = build_defect_profile(row.to_dict())
    bucket_lines = defect_profile.get("bucket_lines", {})
    bucket_defs = [
        ("Cosmetic", "cosmetic"),
        ("Glass", "glass"),
        ("Replacement", "replacement"),
        ("Structural", "structural"),
        ("Mechanical", "mechanical"),
        ("Interior", "interior"),
    ]

    rego_chip_class = "chip good" if rego_status == "Registered" else "chip danger"
    keys_label, keys_chip_class = _keys_pill(row)
    manual_label, manual_chip_class = _manual_pill(row.get("owners_manual"))
    service_label, service_chip_class = _service_pill(row.get("service_history"))
    odometer_value = row.get("odometer_numeric")
    if odometer_value is None or (isinstance(odometer_value, float) and pd.isna(odometer_value)):
        odometer_value = row.get("odometer_reading")
    km_label, km_chip_class = _km_pill(odometer_value, row.get("year"))
    location_badge = f"({location_state})" if location_state else ""
    curve_confidence_label = _curve_confidence_label(row.get("confidence"))
    data_completeness_label = _data_completeness_label(row)
    risk_level_label = _risk_level_label(row, combined_flags, defect_profile)
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
    signal_row_html = "".join(
        [
            '<div class="decision-signal-row">',
            _build_signal_tile(
                "Action",
                action_label,
                f"{_display_action_detail(row.get('action_label'))} Verdict: {verdict_label}.",
                _signal_tone(action_label),
            ),
            _build_signal_tile(
                "Bid status",
                bid_status,
                bid_display["status_detail"],
                _signal_tone(bid_status),
            ),
            _build_signal_tile(
                "Margin",
                profit_pct_display,
                hard_max_safety,
                _margin_signal_tone(row.get("profit_margin_value")),
            ),
            _build_signal_tile(
                "Confidence",
                curve_confidence_label,
                f"Curve {confidence_text}; data {data_completeness_label.lower()}",
                _signal_tone(curve_confidence_label),
            ),
            _build_signal_tile(
                "Risk",
                risk_level_label,
                risk_summary,
                _risk_signal_tone(risk_level_label),
            ),
            "</div>",
        ]
    )

    listing_header_html = "".join(
        [
            '<div class="listing-persistent-header">',
            '<div class="card-top">',
            '<div class="vehicle-title-block">',
            '<div class="vehicle-title">',
            f'<span class="vehicle-title-text">{title_html}</span>',
            f'<span class="vehicle-location">{html.escape(location_badge)}</span>' if location_badge else "",
            "</div>",
            f'<div class="card-top-meta">{html.escape(header_meta)}</div>' if header_meta else "",
            "</div>",
            '<div class="card-top-right">',
            f'<div class="verdict-pill {verdict_pill_class} support-pill context-pill">{html.escape(verdict_label)}</div>',
            '<div class="card-actions">',
            f'<a href="{html.escape(_safe_text(row.get("url"), fallback=""))}" target="_blank">Open</a>'
            if _safe_text(row.get("url"), fallback="") not in ("N/A", "")
            and not _safe_text(row.get("url"), fallback="").lower().lstrip().startswith("javascript:")
            else "",
            "</div>",
            "</div>",
            "</div>",
            "</div>",
        ]
    )

    card_html = "".join(
        [
            f'<div class="vehicle-card {verdict_class} {profit_class}">',
            signal_row_html,
            '<div class="card-metrics">',
            _build_metric_group(
                "Live auction",
                [
                    _build_metric_item("Current price", current_price_display, class_name="primary"),
                    _build_metric_item("Price update", price_update_value, price_update_sub, price_update_class),
                    _build_metric_item("Time left", time_left_display),
                ],
                "auction-group",
            ),
            _build_metric_group(
                "Deal maths",
                [
                    _build_metric_item("Proxy max bid", max_bid_display, bid_display["max_detail"], "primary"),
                    _build_metric_item("Worst profit at proxy max", cap_profit_display, hard_max_safety),
                    _build_metric_item("Current vs proxy max", bid_status, bid_display["status_detail"]),
                    _build_metric_item("Expected finish", expected_auction_display, expected_finish_sub),
                ],
                "money-group",
            ),
            _build_metric_group(
                "Model context",
                [
                    _build_metric_item("Difficulty", flip_difficulty),
                    _build_metric_item("Expected resale", resale_display),
                    _build_metric_item("Profit %", profit_pct_display),
                    _build_metric_item("Score /100", score_100_display),
                ],
                "context-group",
            ),
            "</div>",
            '<div class="chip-row">',
            f'<span class="{km_chip_class}">{html.escape(km_label)}</span>',
            f'<span class="{rego_chip_class}">Rego: {html.escape(rego_text)}</span>',
            f'<span class="{keys_chip_class}">{html.escape(keys_label)}</span>',
            f'<span class="{manual_chip_class}">{html.escape(manual_label)}</span>',
            f'<span class="{service_chip_class}">{html.escape(service_label)}</span>',
            "".join(
                _severity_label_pill_html(
                    label,
                    int(defect_profile.get(key, 0) or 0),
                    tooltip="; ".join(bucket_lines.get(key, [])),
                )
                for label, key in bucket_defs
            ),
            '<span class="chip warn">AMBIG_DRIVETRAIN</span>' if drivetrain_warning else "",
            "</div>",
            "</div>",
        ]
    )
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

    risk_items = []
    if combined_flags:
        risk_items.append(f"Flags: {', '.join(combined_flags[:6])}")
    edge_note = _safe_text(row.get("edge_note"), fallback="")
    if edge_note:
        risk_items.append(edge_note)
    spec_reason = _safe_text(row.get("spec_reason"), fallback="")
    if spec_reason:
        risk_items.append(f"Spec coverage: {spec_reason}")

    with st.container(border=True):
        st.markdown('<div class="listing-shell-marker"></div>', unsafe_allow_html=True)
        st.markdown(listing_header_html, unsafe_allow_html=True)
        overview_tab, curve_tab, comparables_tab, condition_tab, bid_logic_tab = st.tabs(
            ["Overview", "Curve", "Comparables", "Condition", "Bid Logic"]
        )
        with overview_tab:
            st.markdown(card_html, unsafe_allow_html=True)
        with curve_tab:
            _render_curve_tab(row)
        with comparables_tab:
            _render_comparables_tab(row, comps_items)
        with condition_tab:
            _render_condition_tab(row, defect_profile)
        with bid_logic_tab:
            _render_bid_logic_tab(
                row,
                risk_items=risk_items,
            )
    st.markdown('<div class="listing-spacer"></div>', unsafe_allow_html=True)


for _, row in filtered_output.iterrows():
    render_listing_card(row)

if not linked_listing_mode:
    _render_no_curve_section(no_curve_filtered)

st.caption(f"Last refreshed: {time.strftime('%Y-%m-%d %H:%M:%S')}")
