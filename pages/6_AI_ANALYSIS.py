import asyncio

import html

import json

import os

import re

import textwrap

from typing import Any, Iterable, Optional

from urllib.parse import quote_plus



import pandas as pd

import streamlit as st

import streamlit.components.v1 as components



from scripts.ai_price_analysis import (

    compare_active_to_history,

    load_active_listings_within_hours,

    load_historical_sales,

)

from scripts.ai_listing_valuation import (

    load_cached_results as load_ai_cached_results,

    run_ai_listing_analysis,

    update_manual_carsales_data,

)

from scripts.vehicle_updates import coerce_price
from scripts.update_bids import update_bids

from shared.data_loader import ensure_datasets_available

from shared.styling import clean_html, display_banner, inject_global_styles, page_intro



if os.name == "nt":

    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())





st.set_page_config(page_title="AI PRICING ANALYSIS", layout="wide")

inject_global_styles()

display_banner()

page_intro("AI PRICING ANALYSIS", "Blend AI valuations with live market data to rank the sharpest buying opportunities.")



required_files = [

    "vehicle_static_details.csv",

    "active_vehicle_details.csv",

    "ai_verdicts.csv",

    "ai_listing_valuations.csv",

    "sold_cars.csv",

]

missing = ensure_datasets_available(required_files)
if missing:
    st.error(
        "Missing required datasets: "
        + ", ".join(missing)
        + ". Configure `AUTOSNIPER_DATA_URL` or upload the files to `CSV_data/`."
    )
    st.stop()

CONDITION_COLUMNS = [
    "general_condition",
    "key",
    "spare_key",
    "owners_manual",
    "service_history",
    "engine_turns_over",
]


TIMEFRAME_OPTIONS: dict[str, tuple[float, float]] = {

    "Next 24 hours": (0.0, 24.0),

    "Next 48 hours": (0.0, 48.0),

    "Next 72 hours": (0.0, 72.0),

}

DEFAULT_TIMEFRAME = "Next 24 hours"

timeframe_labels = list(TIMEFRAME_OPTIONS.keys())

default_timeframe_index = timeframe_labels.index(DEFAULT_TIMEFRAME)

st.sidebar.header("Time Window")

selected_timeframe_label = st.sidebar.selectbox(

    "Show listings finishing within",

    timeframe_labels,

    index=default_timeframe_index,

)

selected_min_hours, selected_max_hours = TIMEFRAME_OPTIONS[selected_timeframe_label]

if selected_min_hours <= 0:

    time_window_text = f"the next {int(selected_max_hours)} hours"

else:

    time_window_text = (

        f"between {int(selected_min_hours)} and {int(selected_max_hours)} hours from now"

    )

time_window_refresh_text = f"listings finishing within {time_window_text}"

st.caption(

    f"Active listings finishing within {time_window_text} compared with historical sales data."

)





@st.cache_data(ttl=300)

def get_active_listings(min_hours: float, max_hours: float) -> pd.DataFrame:

    return load_active_listings_within_hours(

        csv_path=None,

        min_hours=min_hours,

        max_hours=max_hours,

        include_unknown=True,

    )





@st.cache_data(ttl=1800)

def get_historical_sales() -> pd.DataFrame:

    return load_historical_sales()





@st.cache_data(ttl=120)

def build_comparison_dataframe(min_hours: float, max_hours: float) -> tuple[pd.DataFrame, pd.DataFrame]:

    active_df = get_active_listings(min_hours, max_hours)

    sold_df = get_historical_sales()

    comparison = compare_active_to_history(active_df, sold_df)

    return active_df, comparison





# Manual refresh to pick up latest CSV/manual entries immediately.
if st.button("Refresh data"):

    get_active_listings.clear()
    get_historical_sales.clear()
    build_comparison_dataframe.clear()
    st.rerun()

active_snapshot, comparison_df = build_comparison_dataframe(selected_min_hours, selected_max_hours)
comparison_df = comparison_df.copy()

if "ai_listing_cache" not in st.session_state:
    st.session_state.ai_listing_cache = load_ai_cached_results()

valuations_cache = st.session_state.ai_listing_cache
valuation_columns = [
    "analysis_timestamp",
    "carsales_price_estimate",
    "carsales_price_range",
    "recommended_max_bid",
    "expected_profit",
    "profit_margin_percent",
    "score_out_of_10",
    "confidence_notes",
    "manual_carsales_count",
    "manual_carsales_avg",
    "manual_carsales_avg_odometer",
    "manual_carsales_estimate",
    "manual_instant_offer_estimate",
    "manual_recent_sales_30d",
    "manual_carsales_table",
]
available_columns = [column for column in valuation_columns if column in valuations_cache.columns]
if available_columns:
    valuations_subset = valuations_cache[["url", *available_columns]].copy()
    comparison_df = comparison_df.merge(valuations_subset, on="url", how="left", suffixes=("", "_ai"))
unknown_count = 0
if not active_snapshot.empty and "hours_remaining" in active_snapshot.columns:
    unknown_count = int(active_snapshot["hours_remaining"].isna().sum())
if unknown_count:

    st.info(

        f"{unknown_count} active listing(s) are missing a live countdown on Grays. "
        "They are still shown below with an 'Unknown' time remaining. "
        "Run `scripts/update_bids.py` or use the Active Listings refresh to pull new timers."
    )

condition_lookup = pd.DataFrame()
available_condition_columns = [col for col in CONDITION_COLUMNS if col in active_snapshot.columns]
if available_condition_columns:
    condition_lookup = active_snapshot.set_index("url")[available_condition_columns]

for column in CONDITION_COLUMNS:
    if column not in comparison_df.columns:
        comparison_df[column] = None
    if not condition_lookup.empty and column in condition_lookup.columns:
        comparison_df[column] = comparison_df[column].fillna(
            comparison_df["url"].map(condition_lookup[column])
        )

# Pull manual Carsales fields from the active snapshot so completed rows stay visible.
manual_columns = [
    "manual_carsales_min",
    "manual_carsales_max",
    "manual_instant_offer_estimate",
    "manual_instant_offer_max",
    "manual_carsales_sold_30d",
    "carsales_skipped",
]
available_manual_columns = [col for col in manual_columns if col in active_snapshot.columns]
manual_lookup = active_snapshot.set_index("url")[available_manual_columns] if available_manual_columns else pd.DataFrame()
for column in manual_columns:
    if column not in comparison_df.columns:
        comparison_df[column] = None
    if not manual_lookup.empty and column in manual_lookup.columns:
        comparison_df[column] = comparison_df[column].fillna(
            comparison_df["url"].map(manual_lookup[column])
        )

# Backward-compatible alias for recent sales count.
if "manual_recent_sales_30d" not in comparison_df.columns:
    comparison_df["manual_recent_sales_30d"] = comparison_df.get("manual_carsales_sold_30d")
elif "manual_carsales_sold_30d" in comparison_df.columns:
    comparison_df["manual_recent_sales_30d"] = comparison_df["manual_recent_sales_30d"].fillna(
        comparison_df["manual_carsales_sold_30d"]
    )

# Enforce presence of manual Carsales fields and filter out rows missing them.
for manual_column in ("manual_carsales_min", "manual_instant_offer_estimate"):
    if manual_column not in comparison_df.columns:
        comparison_df[manual_column] = None
if "carsales_skipped" not in comparison_df.columns:
    comparison_df["carsales_skipped"] = False

comparison_df["_manual_min_numeric"] = comparison_df["manual_carsales_min"].apply(coerce_price)
comparison_df["_manual_offer_numeric"] = comparison_df["manual_instant_offer_estimate"].apply(coerce_price)
comparison_df["_has_manual_carsales"] = (
    comparison_df["_manual_min_numeric"].notna()
    & (comparison_df["_manual_min_numeric"] > 0)
    & ~comparison_df["carsales_skipped"].fillna(False).astype(bool)
)
comparison_df = comparison_df[comparison_df["_has_manual_carsales"]].copy()


focus_url = st.session_state.pop("ai_focus_url", None)

# Vehicle-level sidebar filters aligned with Active Listings view.

st.sidebar.markdown("### Vehicle Filters")

hide_engine_issues = st.sidebar.checkbox("Hide vehicles with engine defects", value=True)

hide_unregistered = st.sidebar.checkbox("Hide unregistered vehicles", value=False)

filter_vic_only = st.sidebar.checkbox("Show only VIC listings", value=False)



def _has_engine_issue(text: object) -> bool:

    keywords = [

        "engine light",

        "rough idle",

        "engine oil leak",

        "smoke",

        "seized",

        "blown",

        "won't start",

        "does not start",

        "engine does not turn",

        "no compression",

    ]

    value = str(text or "").lower()

    return any(keyword in value for keyword in keywords)





def _is_unregistered(value: object) -> bool:

    if value is None or (isinstance(value, float) and pd.isna(value)):

        return False

    try:

        return int(float(str(value).strip())) == 0

    except (TypeError, ValueError):

        return False





if hide_engine_issues and "general_condition" in comparison_df.columns:

    engine_mask = ~comparison_df["general_condition"].apply(_has_engine_issue)

    comparison_df = comparison_df[engine_mask].copy()

if hide_unregistered and "no_of_plates" in comparison_df.columns:

    rego_mask = ~comparison_df["no_of_plates"].apply(_is_unregistered)

    comparison_df = comparison_df[rego_mask].copy()

if filter_vic_only and "location" in comparison_df.columns:

    vic_mask = comparison_df["location"].astype(str).str.contains("vic", case=False, na=False)

    comparison_df = comparison_df[vic_mask].copy()



if comparison_df.empty:

    st.info("No active listings found within the selected time window.")

    st.stop()





def trigger_bid_refresh(urls_to_update: list[str] | None, status_key: str) -> None:

    try:

        df, skipped = asyncio.run(update_bids(urls_to_update))

        skipped_count = len(skipped) if skipped else 0

        touched = len(df) if isinstance(df, pd.DataFrame) else 0

        message = f"Updated {touched} listings ({skipped_count} skipped)."

        st.session_state[status_key] = ("success", message)

    except Exception as exc:  # noqa: BLE001

        st.session_state[status_key] = ("error", f"Refresh failed: {exc}")





def format_currency(value: float | None) -> str | None:

    if value is None:

        return None

    return f"${value:,.0f}"





def parse_currency(value: str | float | int | None) -> float | None:

    if value is None:

        return None

    if isinstance(value, float) and pd.isna(value):

        return None

    if isinstance(value, (int, float)):

        return float(value)

    text = str(value).strip()

    if not text:

        return None

    cleaned = text.replace("$", "").replace(",", "")

    numbers = re.findall(r"-?\d+(?:\.\d+)?", cleaned)

    if not numbers:

        return None

    try:

        values = [float(num) for num in numbers]

        return sum(values) / len(values) if values else None

    except ValueError:

        return None





def parse_int(value: str | float | int | None) -> int | None:

    if value is None:

        return None

    if isinstance(value, float) and pd.isna(value):

        return None

    if isinstance(value, (int, float)):

        return int(value)

    text = re.sub(r"[^\d-]", "", str(value))

    if not text:

        return None

    try:

        return int(text)

    except ValueError:

        return None





def coerce_positive_int(value: str | float | int | None) -> int:

    parsed = parse_int(value)

    if parsed is None:

        return 0

    return parsed if parsed > 0 else 0





def _normalise_match_rows(value: object) -> list[dict[str, object]]:

    if isinstance(value, str):

        text = value.strip()

        if not text:

            return []

        try:

            parsed = json.loads(text)

        except json.JSONDecodeError:

            return []

        if isinstance(parsed, list):

            return [entry for entry in parsed if isinstance(entry, dict)]

        return []

    if isinstance(value, tuple):

        value = list(value)

    if isinstance(value, list):

        return [entry for entry in value if isinstance(entry, dict)]

    return []





def has_match_entries(value: object) -> bool:

    return len(_normalise_match_rows(value)) > 0





def parse_odometer_value(value: object) -> float | None:

    if value is None or (isinstance(value, float) and pd.isna(value)):

        return None

    if isinstance(value, (int, float)):

        return float(value)

    text = str(value).lower().replace("km", "").replace(",", "").strip()

    if not text:

        return None

    try:

        return float(text)

    except ValueError:

        return None





def ensure_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:

    missing = [column for column in columns if column not in df.columns]

    for column in missing:

        df[column] = None

    return df





def build_carsales_prompt(row: pd.Series) -> str:

    def safe_get(key: str, default: str = "N/A") -> str:

        value = row.get(key)

        if value is None:

            return default

        if isinstance(value, str) and not value.strip():

            return default

        if pd.isna(value):

            return default

        return str(value)



    year = row.get("year")

    if pd.notna(year):

        try:

            year = int(float(year))

        except Exception:  # noqa: BLE001

            year = safe_get("year")

    else:

        year = safe_get("year")



    lines = [

        f"Year: {year}",

        f"Make: {safe_get('make')}",

        f"Model: {safe_get('model')}",

        f"Variant: {safe_get('variant')}",

        f"Transmission: {safe_get('transmission')}",

        f"Odometer: {safe_get('odometer_reading')} {safe_get('odometer_unit')}",

    ]

    return "\n".join(lines)





def build_carsales_search_url(row: pd.Series) -> str:

    def slug(value: str) -> str:

        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")



    make = row.get("make")

    model = row.get("model")

    year = row.get("year")

    path_parts = []

    if pd.notna(year):

        try:

            year_part = str(int(float(year)))

            if year_part:

                path_parts.append(year_part)

        except Exception:  # noqa: BLE001

            pass

    if pd.notna(make) and str(make).strip():

        path_parts.append(slug(str(make)))

    if pd.notna(model) and str(model).strip():

        path_parts.append(slug(str(model)))



    base = "https://www.carsales.com.au/cars"

    if path_parts:

        url = f"{base}/{'/'.join(path_parts)}/victoria-state/"

    else:

        url = f"{base}/victoria-state/"



    query_terms = []

    year = row.get("year")

    if pd.notna(year):

        try:

            query_terms.append(str(int(float(year))))

        except Exception:  # noqa: BLE001

            pass

    for field in ("make", "model", "variant"):

        value = row.get(field)

        if pd.notna(value) and str(value).strip():

            query_terms.append(str(value).strip())



    if query_terms:

        url = f"{url}?q={quote_plus(' '.join(query_terms))}"

    return url





def build_anchor_id(url: object) -> str:

    if not isinstance(url, str):

        return "listing-top"

    safe = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")

    return f"listing-{safe}" if safe else "listing-top"







def parse_markdown_table(table_text: str) -> Optional[pd.DataFrame]:

    if not table_text or not table_text.strip():

        return None



    lines = [line.strip() for line in table_text.strip().splitlines() if line.strip()]

    if len(lines) < 2:

        return None



    rows = []

    for line in lines:

        if "|" not in line:

            continue

        parts = [cell.strip() for cell in line.strip("|").split("|")]

        rows.append(parts)



    if len(rows) < 2:

        return None



    header = rows[0]

    data_rows = rows[1:]

    if data_rows and all(set(cell) <= {"-", ":"} for cell in data_rows[0]):

        data_rows = data_rows[1:]



    if not data_rows:

        return None



    try:

        df = pd.DataFrame(data_rows, columns=header[: len(data_rows[0])])

    except ValueError:

        return None

    return df



def format_price_value(value: object) -> str:

    if value is None:

        return "—"

    if isinstance(value, float) and pd.isna(value):

        return "—"

    try:

        if isinstance(value, str):

            text = value.strip()

            if not text:

                return "—"

            if text.startswith("$"):

                text = text.replace("$", "").replace(",", "")

            return f"${float(text):,.0f}"

        return f"${float(value):,.0f}"

    except Exception:  # noqa: BLE001

        return str(value)





def format_odometer_diff(value: object) -> str:

    if value is None:

        return "—"

    if isinstance(value, float) and pd.isna(value):

        return "—"

    try:

        return f"{int(round(float(value), 0)):,} km"

    except Exception:  # noqa: BLE001

        return str(value)





def render_historical_table(rows: object, title: str, include_diff: bool = False, expanded: bool = False) -> None:

    if rows is None:

        return

    if isinstance(rows, float) and pd.isna(rows):

        return

    if not isinstance(rows, (list, tuple)):

        return

    if len(rows) == 0:

        return



    df = pd.DataFrame(rows)

    if df.empty:

        return



    rename_map = {

        "year": "Year",

        "make": "Make",

        "model": "Model",

        "variant": "Variant",

        "transmission": "Transmission",

        "odometer_reading": "Odometer",

        "final_price_numeric": "Price",

        "date_sold": "Date Sold",

        "location": "Location",

        "odometer_diff": "Odo Diff",

    }

    df = df.rename(columns=rename_map)



    if "Price" in df.columns:

        df["Price"] = df["Price"].apply(format_price_value)

    if "Odometer" in df.columns:

        def fmt_odo(value):

            if value is None:

                return "—"

            if isinstance(value, float) and pd.isna(value):

                return "—"

            text = str(value).strip()

            if not text:

                return "—"

            if "km" in text.lower():

                return text

            try:

                num = float(text.replace(",", ""))

                return f"{int(round(num)):,} km"

            except Exception:  # noqa: BLE001

                return text



        df["Odometer"] = df["Odometer"].apply(fmt_odo)

    if "Odo Diff" in df.columns and include_diff:

        df["Odo Diff"] = df["Odo Diff"].apply(format_odometer_diff)



    preferred_order = [

        "Year",

        "Make",

        "Model",

        "Variant",

        "Transmission",

        "Odometer",

        "Price",

        "Date Sold",

        "Location",

    ]

    if include_diff and "Odo Diff" in df.columns:

        preferred_order.append("Odo Diff")



    df = df[[col for col in preferred_order if col in df.columns]]



    with st.expander(title, expanded=expanded):

        st.dataframe(df, width="stretch")





def format_listing_odometer(value: object, unit: object) -> str:

    if value is None or (isinstance(value, float) and pd.isna(value)):

        return "—"

    text = str(value).strip()

    if not text:

        return "—"

    if text.lower().endswith("km"):

        return text

    try:

        num = float(text.replace(",", ""))

        suffix = " km"

        if isinstance(unit, str) and unit.strip():

            candidate = unit.strip()

            if candidate.lower() not in {"km", "kilometre", "kilometer"}:

                suffix = f" {candidate}"

        return f"{int(round(num)):,}{suffix}"

    except Exception:  # noqa: BLE001

        return text











def render_listing_header(
    row: pd.Series,
    *,
    wrap_card: bool = True,
    render: bool = True,
) -> str:
    def _clean_text(value: object) -> str | None:
        if value in (None, "") or (isinstance(value, float) and pd.isna(value)):
            return None
        text_value = str(value).strip()
        return text_value or None

    def _safe_label(value: object, default: str = "N/A") -> str:
        cleaned = _clean_text(value)
        return cleaned if cleaned else default

    subtitle_components: list[str] = []
    subtitle_badges: list[str] = []
    meta_fields = [
        ("Transmission", row.get("transmission")),
        ("Fuel", row.get("fuel_type")),
        ("Body", row.get("body_type")),
    ]
    for label, raw_value in meta_fields:
        text_value = _clean_text(raw_value)
        if not text_value:
            continue
        subtitle_components.append(text_value)
        subtitle_badges.append(f"<span>{html.escape(label)}: {html.escape(text_value)}</span>")

    manual_min = coerce_price(row.get("manual_carsales_min"))
    manual_offer = coerce_price(row.get("manual_instant_offer_estimate"))
    manual_skipped_value = row.get("carsales_skipped")
    manual_skipped = False
    if isinstance(manual_skipped_value, str):
        manual_skipped = manual_skipped_value.strip().lower() in ("true", "1", "yes")
    elif manual_skipped_value not in (None, "") and not (
        isinstance(manual_skipped_value, float) and pd.isna(manual_skipped_value)
    ):
        try:
            manual_skipped = bool(manual_skipped_value)
        except Exception:
            manual_skipped = False
    if manual_min and manual_offer and not manual_skipped:
        subtitle_badges.append(
            "<span class='ai-card-condition-badge' style='background: rgba(94,230,167,.18);"
            "border: 1px solid rgba(94,230,167,.45); color: #5EE6A7;'>"
            "✅ Carsales Estimate Complete</span>"
        )

    variant_value = row.get("variant")
    variant_text: str | None = None
    if variant_value not in (None, "") and not (isinstance(variant_value, float) and pd.isna(variant_value)):
        variant_text = str(variant_value).strip()
        for component in subtitle_components:
            if not component:
                continue
            pattern = re.compile(rf"\b{re.escape(component)}\b", re.IGNORECASE)
            variant_text = pattern.sub("", variant_text)
        variant_text = re.sub(r"\s+", " ", variant_text).strip(" ,-/")
        if not variant_text:
            variant_text = None

    title_components: list[str] = []
    year_value = row.get("year")
    if year_value not in (None, "") and not (isinstance(year_value, float) and pd.isna(year_value)):
        try:
            title_components.append(str(int(float(year_value))))
        except Exception:
            title_components.append(str(year_value))

    for field in ("make", "model"):
        cleaned = _clean_text(row.get(field))
        if cleaned:
            title_components.append(cleaned)

    if variant_text:
        title_components.append(variant_text)

    title_text = " ".join(title_components)
    title_text = html.escape(title_text) if title_text else "Untitled listing"

    subtitle_html = (
        f'<div class="ai-card-subtitle">{"".join(subtitle_badges)}</div>'
        if subtitle_badges
        else ""
    )

    url = row.get("url")
    link_html = (
        f'<a class="ai-card-link-button" href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">View Listing</a>'
        if isinstance(url, str) and url.strip()
        else ""
    )

    odo_display = format_listing_odometer(row.get("odometer_reading"), row.get("odometer_unit"))

    condition_summary = _clean_text(row.get("general_condition"))
    if condition_summary:
        condition_summary = textwrap.shorten(condition_summary, width=280, placeholder="...")

    condition_fields = [
        ("Key", "key"),
        ("Spare Key", "spare_key"),
        ("Owner's Manual", "owners_manual"),
        ("Service History", "service_history"),
        ("Engine Turns Over", "engine_turns_over"),
    ]
    condition_badges: list[str] = []
    for label, field in condition_fields:
        value = _clean_text(row.get(field))
        if value:
            condition_badges.append(
                f"<span class='ai-card-condition-badge'><strong>{html.escape(label)}:</strong> {html.escape(value)}</span>"
            )

    condition_section = ""
    if condition_summary or condition_badges:
        summary_html = (
            f"<div class='ai-card-condition-summary'>{html.escape(condition_summary)}</div>"
            if condition_summary
            else ""
        )
        badges_html = (
            "<div class='ai-card-condition-badges'>" + "".join(condition_badges) + "</div>"
            if condition_badges
            else ""
        )
        condition_section = f"<div class='ai-card-conditions'>{summary_html}{badges_html}</div>"

    price_value = row.get("current_price")
    price_text = "--"
    if price_value not in (None, "") and not (isinstance(price_value, float) and pd.isna(price_value)):
        price_text = format_price_value(price_value)
    elif row.get("price"):
        price_text = format_price_value(row.get("price"))

    time_text = "--"
    time_value = row.get("time_remaining_or_date_sold")
    if time_value not in (None, "") and not (isinstance(time_value, float) and pd.isna(time_value)):
        time_str = str(time_value).strip()
        if time_str:
            time_text = time_str
    if time_text == "--":
        hours_remaining = row.get("hours_remaining")
        if hours_remaining not in (None, "") and not (isinstance(hours_remaining, float) and pd.isna(hours_remaining)):
            try:
                time_text = f"{float(hours_remaining):.1f}h"
            except Exception:
                time_text = str(hours_remaining)

    bids_text = "--"
    bids_value = row.get("bids")
    if bids_value not in (None, "") and not (isinstance(bids_value, float) and pd.isna(bids_value)):
        try:
            bids_text = f"{int(float(str(bids_value).replace(',', '').strip())):,}"
        except Exception:
            bids_text = str(bids_value)

    stats = [
        ("Current Price", price_text),
        ("Time Remaining", time_text),
        ("Bids", bids_text),
        ("Location", _safe_label(row.get("location"))),
    ]
    stats_html = "".join(
        f"<div class='ai-card-stat'><div class='ai-card-stat-label'>{html.escape(label)}</div>"
        f"<div class='ai-card-stat-value'>{html.escape(str(value))}</div></div>"
        for label, value in stats
        if value not in (None, "")
    )
    stats_section = f"<div class='ai-card-stats'>{stats_html}</div>" if stats_html else ""

    card_body = ""
    body_parts = [part for part in (condition_section, stats_section) if part]
    if body_parts:
        card_body = f"<div class='ai-card-body'>{''.join(body_parts)}</div>"

    inner_html = f"""
    <div class="ai-card-header">
        <div class="ai-card-title-group">
            <div class="ai-card-title">{title_text}</div>
            {subtitle_html}
        </div>
        <div class="ai-card-actions">
            <div class="ai-card-odometer">
                <div class="ai-card-odometer-label">Odometer</div>
                <div class="ai-card-odometer-value">{odo_display}</div>
            </div>
            {link_html}
        </div>
    </div>
    {card_body}
    """
    if wrap_card:
        rendered_html = f"<div class='ai-card'>{inner_html}</div>"
    else:
        rendered_html = inner_html
    if render:
        st.markdown(rendered_html, unsafe_allow_html=True)
    return rendered_html


def _normalise_text(value: object) -> str:

    if value is None or (isinstance(value, float) and pd.isna(value)):

        return ""

    return re.sub(r"\s+", " ", str(value).strip().lower())





def get_closest_matches(

    row: pd.Series,

    max_odo_diff: float = 20000.0,

) -> tuple[list[dict[str, object]], list[dict[str, float]], list[dict[str, object]]]:

    base_odo = parse_odometer_value(row.get("odometer_numeric"))

    if base_odo is None:

        base_odo = parse_odometer_value(row.get("odometer_reading"))



    target_make = _normalise_text(row.get("make"))

    target_model = _normalise_text(row.get("model"))

    target_variant = _normalise_text(row.get("variant"))



    combined_entries: list[dict[str, object]] = []

    seen_entry_keys: set[tuple] = set()

    seen_url_index: dict[str, int] = {}

    def _normalise_url(value: object) -> str | None:

        if value is None or (isinstance(value, float) and pd.isna(value)):

            return None

        text = str(value).strip()

        if not text:

            return None

        return text.rstrip("/").lower()

    def _entry_url_key(entry: dict[str, object]) -> str | None:

        for key in ("_source_url", "source_url", "url", "URL"):

            candidate = entry.get(key)

            normalised = _normalise_url(candidate)

            if normalised:

                return normalised

        return None

    def _has_odometer_diff(entry: dict[str, object]) -> bool:

        diff_value = entry.get("Odo Diff", entry.get("odometer_diff"))

        if diff_value is None:

            return False

        if isinstance(diff_value, float) and pd.isna(diff_value):

            return False

        return bool(str(diff_value).strip())

    for source_key in ("historical_matches_rows", "historical_close_matches_rows"):

        source_rows = _normalise_match_rows(row.get(source_key))

        if not source_rows:

            continue

        for entry in source_rows:

            url_key = _entry_url_key(entry)

            if url_key:

                existing_index = seen_url_index.get(url_key)

                if existing_index is not None:

                    existing_entry = combined_entries[existing_index]

                    if _has_odometer_diff(entry) and not _has_odometer_diff(existing_entry):

                        combined_entries[existing_index] = entry

                    continue

                seen_url_index[url_key] = len(combined_entries)

                combined_entries.append(entry)

                continue

            entry_key = tuple(sorted(entry.items()))

            if entry_key in seen_entry_keys:

                continue

            seen_entry_keys.add(entry_key)

            combined_entries.append(entry)



    processed_rows: list[dict[str, object]] = []

    summary_records: list[dict[str, float]] = []

    fallback_candidates: list[dict[str, object]] = []

    all_candidates: list[dict[str, object]] = []



    for entry in combined_entries:

        entry_make = _normalise_text(entry.get("Make") or entry.get("make"))

        entry_model = _normalise_text(entry.get("Model") or entry.get("model"))

        entry_variant = _normalise_text(entry.get("Variant") or entry.get("variant"))



        if target_make and entry_make and entry_make != target_make:

            continue

        if target_model and entry_model and entry_model != target_model:

            continue

        if target_variant and entry_variant and target_variant not in entry_variant and entry_variant not in target_variant:

            continue



        entry_odo_text = entry.get("Odometer") or entry.get("odometer_reading")

        match_odo = parse_odometer_value(entry_odo_text)



        odo_diff = None

        if base_odo is not None and match_odo is not None:

            odo_diff = match_odo - base_odo

        else:

            diff_value = parse_odometer_value(entry.get("Odo Diff") or entry.get("odometer_diff"))

            odo_diff = diff_value if diff_value is not None else None

        if base_odo is not None and odo_diff is None:

            continue



        price_input = entry.get("Price") or entry.get("final_price_numeric")

        price_val = parse_currency(price_input)

        if price_val is None:

            continue



        mapped_entry = {

            "year": entry.get("Year") or entry.get("year"),

            "make": entry.get("Make") or entry.get("make"),

            "model": entry.get("Model") or entry.get("model"),

            "variant": entry.get("Variant") or entry.get("variant"),

            "transmission": entry.get("Transmission") or entry.get("transmission"),

            "odometer_reading": entry_odo_text,

            "final_price_numeric": price_val,

            "date_sold": entry.get("Date Sold") or entry.get("date_sold"),

            "location": entry.get("Location") or entry.get("location"),

            "odometer_diff": odo_diff,

        }



        abs_diff = abs(odo_diff) if odo_diff is not None else float("inf")

        candidate = {

            "entry": mapped_entry,

            "price": price_val,

            "abs_diff": abs_diff,

            "odo": match_odo,

        }

        all_candidates.append(candidate)



        if abs_diff <= max_odo_diff:

            processed_rows.append(mapped_entry)

            summary_records.append({"price": price_val, "odo_diff": abs_diff})

        else:

            fallback_candidates.append(candidate)



    processed_rows.sort(key=lambda entry: abs(entry.get("odometer_diff")) if entry.get("odometer_diff") is not None else float("inf"))

    summary_records.sort(key=lambda item: item["odo_diff"])



    if not processed_rows and fallback_candidates:

        fallback_candidates.sort(key=lambda item: item["abs_diff"])

        top_candidates = fallback_candidates[:2]

        processed_rows = [item["entry"] for item in top_candidates]

        summary_records = [

            {

                "price": item["price"],

                "odo_diff": item["abs_diff"],

            }

            for item in top_candidates

        ]



    def sort_all_candidates(item: dict[str, object]) -> tuple[int, float]:

        odo = item.get("odo")

        if odo is None or (isinstance(odo, float) and pd.isna(odo)):

            return (1, float("inf"))

        try:

            return (0, float(odo))

        except (TypeError, ValueError):

            return (1, float("inf"))



    all_rows = [candidate["entry"] for candidate in sorted(all_candidates, key=sort_all_candidates)]



    return processed_rows, summary_records, all_rows





def has_displayable_history(row: pd.Series) -> bool:

    try:

        _, _, all_matches = get_closest_matches(row)

    except Exception:  # noqa: BLE001

        return False

    return bool(all_matches)





def render_closest_matches_section(row: pd.Series) -> None:

    matches, summaries, all_matches = get_closest_matches(row)

    if not all_matches:

        st.caption("No historical auction results found for this vehicle yet.")

        return



    def make_key(entry: dict[str, object]) -> tuple:

        return tuple(sorted(entry.items()))



    closest_keys = {make_key(entry) for entry in matches}



    def diff_value(entry: dict[str, object]) -> float:

        diff = entry.get("odometer_diff")

        if diff is None or (isinstance(diff, float) and pd.isna(diff)):

            return float("inf")

        try:

            return abs(float(diff))

        except (TypeError, ValueError):

            return float("inf")



    highlight_entry = min(all_matches, key=diff_value) if all_matches else None

    highlight_key = make_key(highlight_entry) if highlight_entry else None



    table_rows: list[dict[str, object]] = []

    for entry in all_matches:

        entry_copy = entry.copy()

        row_key = make_key(entry)

        entry_copy["_row_key"] = row_key

        entry_copy["_match_type"] = "Closest" if row_key in closest_keys else "Similar"

        entry_copy["_highlight"] = row_key == highlight_key

        table_rows.append(entry_copy)



    df = pd.DataFrame(table_rows)



    rename_map = {

        "year": "Year",

        "make": "Make",

        "model": "Model",

        "variant": "Variant",

        "transmission": "Transmission",

        "odometer_reading": "Odometer",

        "final_price_numeric": "Price",

        "date_sold": "Date Sold",

        "location": "Location",

        "odometer_diff": "Odo Diff",

    }

    df = df.rename(columns=rename_map)



    def format_odometer_value(value: object) -> str:

        if value is None or (isinstance(value, float) and pd.isna(value)):

            return "—"

        try:

            return f"{int(round(float(value))):,} km"

        except (TypeError, ValueError):

            text = str(value).strip()

            return text if text else "—"



    if "Price" in df.columns:

        df["Price"] = df["Price"].apply(format_price_value)

    if "Odometer" in df.columns:

        df["Odometer"] = df["Odometer"].apply(format_odometer_value)

    if "Odo Diff" in df.columns:

        df["Odo Diff"] = df["Odo Diff"].apply(format_odometer_diff)



    df["Best Match"] = df["_highlight"].apply(lambda val: "Yes" if val else "")

    df["Match Type"] = df["_match_type"]



    display_columns = [

        col

        for col in [

            "Best Match",

            "Match Type",

            "Year",

            "Make",

            "Model",

            "Variant",

            "Transmission",

            "Odometer",

            "Odo Diff",

            "Price",

            "Date Sold",

            "Location",

        ]

        if col in df.columns

    ]

    display_df = df[display_columns]



    def highlight_row(row: pd.Series) -> list[str]:

        if row.get("Best Match") == "Yes":

            return ["background-color: rgba(72, 72, 88, 0.22);"] * len(row)

        if row.get("Match Type") == "Closest":

            return ["background-color: rgba(72, 72, 88, 0.12);"] * len(row)

        return ["" for _ in row]



    styled_df = display_df.style.apply(highlight_row, axis=1)

    st.dataframe(styled_df, width="stretch")



    price_values = [

        entry.get("final_price_numeric")

        for entry in all_matches

        if entry.get("final_price_numeric") is not None and not pd.isna(entry.get("final_price_numeric"))

    ]

    if price_values:

        min_price = min(price_values)

        max_price = max(price_values)

        best_price = highlight_entry.get("final_price_numeric") if highlight_entry else None



        summary_cols = st.columns(3)

        summary_cols[0].metric("Lowest auction price", format_price_value(min_price))

        summary_cols[1].metric("Highest auction price", format_price_value(max_price))

        summary_cols[2].metric(

            "Closest match price",

            format_price_value(best_price) if best_price is not None else "—",

        )









def refresh_ai_cache() -> None:

    st.session_state.ai_listing_cache = load_ai_cached_results()





if "ai_refresh_status" in st.session_state:

    level, message = st.session_state.pop("ai_refresh_status")

    notifier = getattr(st, level, st.info)

    notifier(message)



st.sidebar.header("AI Pricing Filters")

min_matches = st.sidebar.slider("Minimum historical matches", 0, 20, 1)

min_discount = st.sidebar.number_input(

    "Highlight underpriced listings ($ discount)",

    min_value=0.0,

    value=0.0,

    step=100.0,

)

min_variant_quality = st.sidebar.slider(

    "Minimum variant similarity",

    0.0,

    1.0,

    0.0,

    0.05,

)







def _value_has_data(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return False
        return True
    return True


def _first_non_empty(*values: object) -> str:
    for value in values:
        if _value_has_data(value):
            return str(value).strip()
    return ""


def build_ai_input_snapshot(listing_row: Optional[pd.Series]) -> dict[str, Any]:
    if listing_row is None:
        return {}
    snapshot: dict[str, Any] = {
        "year": listing_row.get("year"),
        "make": listing_row.get("make"),
        "model": listing_row.get("model"),
        "variant": listing_row.get("variant"),
        "location": listing_row.get("location"),
        "current_bid": listing_row.get("current_price"),
        "hours_remaining": listing_row.get("hours_remaining"),
        "odometer": listing_row.get("odometer_reading"),
        "odometer_unit": listing_row.get("odometer_unit"),
        "historical_match_count": listing_row.get("historical_match_count"),
        "historical_median": listing_row.get("historical_price_median"),
        "historical_mean": listing_row.get("historical_price_mean"),
        "historical_min": listing_row.get("historical_price_min"),
        "historical_max": listing_row.get("historical_price_max"),
        "historical_median_discount": listing_row.get("median_discount"),
    }
    manual_snapshot = {
        "comparable_count": listing_row.get("manual_carsales_count"),
        "carsales_manual_estimate": listing_row.get("manual_carsales_estimate")
        or listing_row.get("manual_carsales_avg"),
        "carsales_average_odometer": listing_row.get("manual_carsales_avg_odometer"),
        "instant_offer_estimate": listing_row.get("manual_instant_offer_estimate"),
        "recent_sales_30d": listing_row.get("manual_recent_sales_30d"),
    }
    manual_clean = {key: value for key, value in manual_snapshot.items() if _value_has_data(value)}
    if manual_clean:
        snapshot["carsales_manual_snapshot"] = manual_clean
    return {key: value for key, value in snapshot.items() if _value_has_data(value)}


def render_ai_result(url: str, listing_row: Optional[pd.Series] = None) -> None:

    cache_df = st.session_state.ai_listing_cache

    has_record = not cache_df.empty and url in cache_df["url"].values
    record = cache_df[cache_df["url"] == url].iloc[0] if has_record else None
    record_data = record.to_dict() if record is not None else {}

    listing_manual_estimate = None
    listing_manual_avg = None
    listing_manual_avg_odo = None
    listing_manual_count = None
    listing_manual_instant = None
    listing_manual_recent = None
    listing_manual_table = None
    if listing_row is not None:
        listing_manual_estimate = listing_row.get("manual_carsales_estimate")
        listing_manual_avg = listing_row.get("manual_carsales_avg")
        listing_manual_avg_odo = listing_row.get("manual_carsales_avg_odometer")
        listing_manual_count = listing_row.get("manual_carsales_count")
        listing_manual_instant = listing_row.get("manual_instant_offer_estimate")
        listing_manual_recent = listing_row.get("manual_recent_sales_30d")
        listing_manual_table = listing_row.get("manual_carsales_table")

    manual_override_record = record_data.get("manual_carsales_estimate") or record_data.get("manual_carsales_avg")
    manual_override_display = (
        manual_override_record
        or listing_manual_estimate
        or listing_manual_avg
    )

    st.markdown("**AI Carsales Check**")

    if not has_record:
        st.caption("No AI Carsales analysis yet.")
    else:
        timestamp = record.get("analysis_timestamp")
        if pd.notna(timestamp):
            st.caption(f"Last updated: {timestamp}")

        col1, col2, col3 = st.columns(3)

        estimate_label = "Carsales Estimate"
        if manual_override_record:
            estimate_label += " (Manual)"

        col1.metric(estimate_label, manual_override_display or record.get("carsales_price_estimate") or "N/A")
        col2.metric("Recommended Max Bid", record.get("recommended_max_bid") or "N/A")
        col3.metric("Expected Profit", record.get("expected_profit") or "N/A")

        if manual_override_record:
            st.caption("Manual Carsales override active. Clear the override to fall back to AI estimates.")

        margin = record.get("profit_margin_percent")
        score = record.get("score_out_of_10")
        range_text = record.get("carsales_price_range")

        info_line_parts = []
        if margin and pd.notna(margin):
            info_line_parts.append(f"Margin: {margin}")
        if score and pd.notna(score):
            info_line_parts.append(f"Score: {score}/10")
        if range_text and pd.notna(range_text):
            info_line_parts.append(f"Range: {range_text}")
        if info_line_parts:
            st.write(" | ".join(info_line_parts))

        notes = record.get("confidence_notes")
        if isinstance(notes, str) and notes.strip():
            st.markdown("Confidence notes:")
            for note in [n.strip() for n in notes.split(";") if n.strip()]:
                st.markdown(f"- {note}")

        instant_offer = record.get("manual_instant_offer_estimate")
        if instant_offer:
            st.caption(f"Instant offer estimate: {instant_offer}")

        recent_sales = record.get("manual_recent_sales_30d")
        if recent_sales not in (None, "", "nan"):
            st.caption(f"Similar cars sold (30 days): {recent_sales}")

    def _parse_float_from_text(text: str | None) -> Optional[float]:

        if not text:

            return None

        cleaned = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))

        if not cleaned:

            return None

        try:

            return float(cleaned[0])

        except ValueError:

            return None

    def _parse_int_from_text(text: str | None) -> Optional[int]:

        value = _parse_float_from_text(text)

        return int(value) if value is not None else None

    safe_key = re.sub(r"\W+", "_", url or "manual")
    manual_default_value = _first_non_empty(
        manual_override_display,
        record_data.get("carsales_price_estimate"),
        listing_manual_estimate,
        listing_manual_avg,
    )
    existing_avg_odometer_text = _first_non_empty(listing_manual_avg_odo, record_data.get("manual_carsales_avg_odometer"))
    existing_count_text = _first_non_empty(listing_manual_count, record_data.get("manual_carsales_count"))
    existing_instant_text = _first_non_empty(listing_manual_instant, record_data.get("manual_instant_offer_estimate"))
    existing_recent_text = _first_non_empty(listing_manual_recent, record_data.get("manual_recent_sales_30d"))
    existing_table_text = _first_non_empty(listing_manual_table, record_data.get("manual_carsales_table"))

    manual_range_input = st.text_input(
        "Carsales estimate ($)",
        value=manual_default_value,
        key=f"manual-estimate-{safe_key}",
        help="Enter the Carsales valuation or a range such as $12,000-$14,000.",
    )
    save_manual = st.button("Save Carsales estimate", key=f"save-manual-{safe_key}")

    if save_manual:
        if not url:
            st.error("Listing URL missing; unable to save manual data.")
        else:
            avg_value = _parse_float_from_text(existing_avg_odometer_text)
            comparable_count_val = _parse_int_from_text(existing_count_text)
            recent_sales_val = _parse_int_from_text(existing_recent_text)
            try:
                update_manual_carsales_data(
                    url=url,
                    price_estimate=manual_range_input.strip() or None,
                    avg_odometer=avg_value,
                    table_raw=existing_table_text or "",
                    instant_offer_estimate=existing_instant_text or None,
                    recent_sales_30d=recent_sales_val,
                    comparable_count=comparable_count_val,
                )
            except Exception as exc:
                st.error(f"Failed to save manual Carsales data: {exc}")
            else:
                refresh_ai_cache()
                st.success("Manual Carsales override saved.")
                st.rerun()

    if listing_row is not None:

        snapshot_data = build_ai_input_snapshot(listing_row)

        if snapshot_data:

            with st.expander("AI input snapshot"):

                st.caption("Data that fed the Carsales AI valuation prompt.")

                pretty_snapshot = json.loads(json.dumps(snapshot_data, default=str))

                st.json(pretty_snapshot)

comparison_df["_match_count_numeric"] = comparison_df["historical_match_count"].apply(coerce_positive_int)

comparison_df["_close_match_count_numeric"] = comparison_df["historical_close_match_count"].apply(coerce_positive_int)

comparison_df["_has_match_rows"] = comparison_df["historical_matches_rows"].apply(has_match_entries)

comparison_df["_has_close_rows"] = comparison_df["historical_close_matches_rows"].apply(has_match_entries)

comparison_df["_effective_match_count"] = comparison_df[["_match_count_numeric", "_close_match_count_numeric"]].max(axis=1)

comparison_df["_has_displayable_history"] = comparison_df.apply(has_displayable_history, axis=1)



matched_count = int(comparison_df["_has_displayable_history"].sum())

total_active = len(comparison_df)

st.markdown(

    f"**{matched_count}** of **{total_active}** active listings have historical pricing data."

)



current_urls = comparison_df["url"].dropna().tolist()

refresh_cols = st.columns(2)

with refresh_cols[0]:

    if st.button("Refresh listings in current window"):

        if not current_urls:

            st.info("No URLs to refresh.")

        else:

            with st.spinner(f"Refreshing {time_window_refresh_text}..."):

                trigger_bid_refresh(current_urls, "ai_refresh_status")

            st.rerun()

with refresh_cols[1]:

    st.caption("Use the dashboard refresh for a full update.")



matched_df = comparison_df[

    comparison_df["_has_displayable_history"]

    & (comparison_df["_effective_match_count"] >= min_matches)

].copy()

matched_df = ensure_columns(matched_df, [

    "historical_match_count",

    "variant_match_quality",

    "priced_below_history",

    "median_discount",

    "historical_price_median",

    "historical_price_mean",

    "historical_price_min",

    "historical_price_max",

    "historical_close_match_count",

    "historical_close_price_median",

    "historical_close_price_mean",

    "historical_close_price_min",

    "historical_close_price_max",

    "historical_close_avg_odometer_diff",

    "price_vs_median",

    "price_vs_close_median",

    "close_median_discount",

    "priced_below_history",

    "priced_below_close_history",

    "current_price",

    "time_remaining_or_date_sold",

    "odometer_numeric",

    "historical_matches_rows",

    "historical_close_matches_rows",

] )

if min_variant_quality > 0:

    matched_df = matched_df[

        matched_df["variant_match_quality"].fillna(0) >= min_variant_quality

    ].copy()



underpriced_df = matched_df[matched_df["priced_below_history"].isin([True])].copy()

underpriced_df = ensure_columns(underpriced_df, [

    "historical_match_count",

    "median_discount",

    "historical_price_median",

    "historical_close_match_count",

    "historical_close_price_median",

    "historical_close_avg_odometer_diff",

    "hours_remaining",

    "current_price",

    "variant_match_quality",

    "time_remaining_or_date_sold",

    "price_vs_close_median",

    "close_median_discount",

    "priced_below_close_history",

    "historical_matches_rows",

    "historical_close_matches_rows",

] )

if min_discount > 0:

    underpriced_df = underpriced_df[

        underpriced_df["median_discount"].fillna(0) >= min_discount

    ].copy()

if "median_discount" in underpriced_df.columns:

    underpriced_df = underpriced_df.sort_values(

        by=["median_discount", "historical_match_count"],

        ascending=[False, False],

    )



no_history_df = comparison_df[~comparison_df["_has_displayable_history"]].copy()

no_history_df = ensure_columns(no_history_df, [

    "hours_remaining",

    "current_price",

    "location",

    "time_remaining_or_date_sold",

    "historical_close_match_count",

    "historical_close_price_median",

    "historical_close_avg_odometer_diff",

    "price_vs_close_median",

    "historical_matches_rows",

    "historical_close_matches_rows",

] )



tabs = st.tabs(["Under Historical Pricing", "No Historical Data"])



with tabs[0]:

    if underpriced_df.empty:

        st.info("No listings meet the current filters.")

    else:

        for _, row in underpriced_df.iterrows():

            anchor_id = build_anchor_id(row.get("url"))

            st.markdown(f"<div id='{anchor_id}'></div>", unsafe_allow_html=True)

            with st.container():

                st.markdown("<div class='ai-card ai-listing-wrapper'>", unsafe_allow_html=True)

                header_html = render_listing_header(row, wrap_card=False, render=False)
                st.markdown(header_html, unsafe_allow_html=True)

                st.markdown("### Auction Data")
                render_closest_matches_section(row)



                st.markdown("### Verdict")

                action_col, rerun_col = st.columns([1, 1])

                rendered = False

                if action_col.button(

                    "Run AI Carsales Check",

                    key=f"ai_run_{row['url']}"

                ):

                    with st.spinner("Consulting AI for Carsales pricing..."):

                        result = run_ai_listing_analysis(row)

                    if result.get("error"):

                        st.error(result["error"])

                    else:

                        refresh_ai_cache()

                        st.success(

                            "AI pricing analysis completed."

                            if not result.get("cached")

                            else "Loaded cached AI pricing analysis."

                        )

                        render_ai_result(row["url"], row)

                        rendered = True



                if rerun_col.button(

                    "Re-run AI Analysis",

                    key=f"ai_rerun_{row['url']}"

                ):

                    with st.spinner("Refreshing AI valuation..."):

                        result = run_ai_listing_analysis(row, force_refresh=True)

                    if result.get("error"):

                        st.error(result["error"])

                    else:

                        refresh_ai_cache()

                        st.success("AI pricing analysis refreshed.")

                        render_ai_result(row["url"], row)

                        rendered = True

                st.markdown("</div>", unsafe_allow_html=True)



                if not rendered:

                    render_ai_result(row["url"], row)



            if focus_url and isinstance(row.get("url"), str) and row["url"] == focus_url:

                components.html(

                    f"""

                    <script>

                    const el = document.getElementById('{anchor_id}');

                    if (el) {{ el.scrollIntoView({{ behavior: 'auto', block: 'start' }}); }}

                    </script>

                    """,

                    height=0,

                )

                focus_url = None

with tabs[1]:

    if no_history_df.empty:

        st.info("Every listing has some historical context.")

    else:

        for _, row in no_history_df.iterrows():

            anchor_id = build_anchor_id(row.get("url"))

            st.markdown(f"<div id='{anchor_id}'></div>", unsafe_allow_html=True)

            with st.container():

                st.markdown("<div class='ai-card ai-listing-wrapper'>", unsafe_allow_html=True)

                header_html = render_listing_header(row, wrap_card=False, render=False)
                st.markdown(header_html, unsafe_allow_html=True)

                st.markdown("### Auction Data")
                render_closest_matches_section(row)



                st.markdown("### Verdict")

                action_col, rerun_col = st.columns([1, 1])

                rendered = False

                if action_col.button(

                    "Run AI Carsales Check",

                    key=f"ai_run_nohist_{row['url']}",

                ):

                    with st.spinner("Consulting AI for Carsales pricing..."):

                        result = run_ai_listing_analysis(row)

                    if result.get("error"):

                        st.error(result["error"])

                    else:

                        refresh_ai_cache()

                        st.success(

                            "AI pricing analysis completed."

                            if not result.get("cached")

                            else "Loaded cached AI pricing analysis."

                        )

                        render_ai_result(row["url"], row)

                        rendered = True



                if rerun_col.button(

                    "Re-run AI Analysis",

                    key=f"ai_rerun_nohist_{row['url']}",

                ):

                    with st.spinner("Refreshing AI valuation..."):

                        result = run_ai_listing_analysis(row, force_refresh=True)

                    if result.get("error"):

                        st.error(result["error"])

                    else:

                        refresh_ai_cache()

                        st.success("AI pricing analysis refreshed.")

                        render_ai_result(row["url"], row)

                        rendered = True



                if not rendered:

                    render_ai_result(row["url"], row)

                st.markdown("</div>", unsafe_allow_html=True)



            if focus_url and isinstance(row.get("url"), str) and row["url"] == focus_url:

                components.html(

                    f"""

                    <script>

                    const el = document.getElementById('{anchor_id}');

                    if (el) {{ el.scrollIntoView({{ behavior: 'auto', block: 'start' }}); }}

                    </script>

                    """,

                    height=0,

                )

                focus_url = None

