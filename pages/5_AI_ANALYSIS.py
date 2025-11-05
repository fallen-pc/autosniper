import asyncio
import html
import json
import os
import re
from typing import Iterable, Optional
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
from scripts.update_bids import update_bids
from shared.data_loader import ensure_datasets_available
from shared.styling import clean_html, display_banner, inject_global_styles

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


st.set_page_config(page_title="AI PRICING ANALYSIS", layout="wide")
inject_global_styles()
display_banner()
st.markdown(
    clean_html(
        """
        <h1 style="text-align:center;">AI PRICING ANALYSIS</h1>
        """
    ),
    unsafe_allow_html=True,
)
st.markdown(
    "<p class='autosniper-tagline'>Blend AI valuations with live market data to rank the sharpest buying opportunities.</p>",
    unsafe_allow_html=True,
)

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

MANUAL_COLS = [
    "manual_carsales_count",
    "manual_carsales_min",
    "manual_carsales_max",
    "manual_carsales_avg",
    "manual_carsales_avg_odometer",
    "manual_carsales_estimate",
    "manual_instant_offer_estimate",
    "manual_recent_sales_30d",
    "manual_carsales_table",
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
    )


@st.cache_data(ttl=1800)
def get_historical_sales() -> pd.DataFrame:
    return load_historical_sales()


@st.cache_data(ttl=120)
def build_comparison_dataframe(min_hours: float, max_hours: float) -> pd.DataFrame:
    active_df = get_active_listings(min_hours, max_hours)
    sold_df = get_historical_sales()
    return compare_active_to_history(active_df, sold_df)


comparison_df = build_comparison_dataframe(selected_min_hours, selected_max_hours).copy()
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


def format_manual_carsales_json(row: pd.Series) -> str:
    data = {}
    count = parse_int(row.get("manual_carsales_count"))
    min_price = parse_currency(row.get("manual_carsales_min"))
    max_price = parse_currency(row.get("manual_carsales_max"))
    avg_price = parse_currency(row.get("manual_carsales_avg"))
    estimate_price = parse_currency(row.get("manual_carsales_estimate"))
    instant_offer = parse_currency(row.get("manual_instant_offer_estimate"))
    recent_sales = parse_int(row.get("manual_recent_sales_30d"))
    estimate_raw = row.get("manual_carsales_estimate")
    instant_raw = row.get("manual_instant_offer_estimate")

    if count is not None:
        data["comparable_count"] = count
    if min_price is not None:
        data["price_min"] = format_currency(min_price)
    if max_price is not None:
        data["price_max"] = format_currency(max_price)
    if avg_price is not None:
        data["price_average"] = format_currency(avg_price)
    if isinstance(estimate_raw, str) and estimate_raw.strip():
        data["price_estimate"] = estimate_raw.strip()
    elif estimate_price is not None:
        data["price_estimate"] = format_currency(estimate_price)
    if isinstance(instant_raw, str) and instant_raw.strip():
        data["instant_offer_estimate"] = instant_raw.strip()
    elif instant_offer is not None:
        data["instant_offer_estimate"] = format_currency(instant_offer)
    if recent_sales is not None:
        data["recent_sales_30d"] = int(recent_sales)

    return json.dumps(data, indent=2) if data else ""


def parse_manual_carsales_input(
    raw_text: str,
) -> tuple[int | None, float | None, float | None, float | None, float | None, str, float | None]:
    if not raw_text or not raw_text.strip():
        raise ValueError("Carsales response cannot be empty.")

    text = raw_text.strip()
    data: dict[str, str | int | float] | None = None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]
        if isinstance(parsed, dict):
            data = parsed
    except json.JSONDecodeError:
        data = None

    def parse_kilometres(value: str | float | int | None) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text_value = str(value).lower().replace("km", "").replace(",", "").strip()
        if not text_value:
            return None
        try:
            return float(text_value)
        except ValueError:
            return None

    count_val = None
    min_val = None
    max_val = None
    avg_val = None
    estimate_val = None
    avg_odo_val = None

    if data is not None:
        def grab(*keys: str) -> str | int | float | None:
            for key in keys:
                if key in data and data[key] not in (None, ""):
                    return data[key]
            return None

        count_val = grab("comparable_count", "count", "listings", "vehicles")
        min_val = grab("price_min", "min_price", "minimum_price", "minimum")
        max_val = grab("price_max", "max_price", "maximum_price", "maximum")
        avg_val = grab("price_average", "average_price", "avg_price", "mean_price", "average")
        estimate_val = grab("price_estimate", "estimate_price", "carsales_estimate")
        avg_odo_val = grab("odometer_average", "average_odometer", "avg_odometer")
    else:
        count_match = re.search(r"(comparable|listing|vehicle|count)[^\d]*(\d+)", text, re.IGNORECASE)
        if count_match:
            count_val = count_match.group(2)
        min_match = re.search(r"(?:min(?:imum)?)\D*([$]?\d[\d,]*(?:\.\d+)?)", text, re.IGNORECASE)
        max_match = re.search(r"(?:max(?:imum)?)\D*([$]?\d[\d,]*(?:\.\d+)?)", text, re.IGNORECASE)
        avg_match = re.search(r"(?:avg|average|mean)\D*([$]?\d[\d,]*(?:\.\d+)?)", text, re.IGNORECASE)
        min_val = min_match.group(1) if min_match else None
        max_val = max_match.group(1) if max_match else None
        avg_val = avg_match.group(1) if avg_match else None

    count_int = parse_int(count_val)
    min_price = parse_currency(min_val)
    max_price = parse_currency(max_val)
    avg_price = parse_currency(avg_val)
    estimate_price = parse_currency(estimate_val)
    avg_odometer = parse_kilometres(avg_odo_val) if avg_odo_val is not None else None

    extracted_prices: list[float] = []
    extracted_odometers: list[float] = []

    for line in text.splitlines():
        stripped = line.strip()
        if "|" not in stripped:
            continue
        cells = [cell.strip() for cell in stripped.split("|") if cell.strip()]
        if not cells or cells[0].lower() == "year":
            continue
        if any("input vehicle" in cell.lower() for cell in cells):
            continue
        if len(cells) >= 2:
            price_candidate = cells[-1]
            if "$" in price_candidate:
                price_val = parse_currency(price_candidate)
                if price_val is not None:
                    extracted_prices.append(price_val)
            odo_candidate = cells[-2] if len(cells) >= 2 else None
            odo_val = parse_kilometres(odo_candidate)
            if odo_val is not None:
                extracted_odometers.append(odo_val)

    for line in text.splitlines():
        lowered = line.lower()
        if "input vehicle" in lowered or "|" in line:
            continue
        if "$" in line:
            price_matches = re.findall(r"\$[\d,]*(?:\.\d+)?", line)
            for match in price_matches:
                price_value = parse_currency(match)
                if price_value is not None:
                    extracted_prices.append(price_value)
            continue
        if "km" in lowered:
            odo_match = re.search(r"([\d,]+)\s*km", lowered)
            if odo_match:
                odo_val = parse_kilometres(odo_match.group(1))
                if odo_val is not None:
                    extracted_odometers.append(odo_val)
            continue
        if any(keyword in lowered for keyword in ("kilometre", "odometer", "vin", "year", "model", "variant")):
            continue
        match = re.fullmatch(r"\d[\d,]*(?:\.\d+)?", line.strip())
        if match:
            value = parse_currency(match.group())
            if value is not None and value >= 1000:
                extracted_prices.append(value)

    if extracted_prices:
        extracted_prices = [price for price in extracted_prices if price is not None]

    if avg_price is None and extracted_prices:
        avg_price = sum(extracted_prices) / len(extracted_prices)
        if min_price is None:
            min_price = min(extracted_prices)
        if max_price is None:
            max_price = max(extracted_prices)
        if count_int is None:
            count_int = len(extracted_prices)
    else:
        if avg_price is not None:
            if min_price is None:
                min_price = avg_price
            if max_price is None:
                max_price = avg_price
        elif extracted_prices:
            pass

    if min_price is None:
        min_price = avg_price
    if max_price is None:
        max_price = avg_price
    if count_int is None:
        count_int = len(extracted_prices) if extracted_prices else 1

    if avg_odometer is None and extracted_odometers:
        avg_odometer = sum(extracted_odometers) / len(extracted_odometers)

    if estimate_price is None:
        estimate_price = avg_price

    return count_int, min_price, max_price, avg_price, avg_odometer, raw_text.strip(), estimate_price

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
        st.dataframe(df, use_container_width=True)


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





def render_listing_header(row: pd.Series) -> None:
    subtitle_components: list[str] = []
    subtitle_badges: list[str] = []
    meta_fields = [
        ("Transmission", row.get("transmission")),
        ("Fuel", row.get("fuel_type")),
        ("Body", row.get("body_type")),
    ]
    for label, raw_value in meta_fields:
        if raw_value in (None, "") or (isinstance(raw_value, float) and pd.isna(raw_value)):
            continue
        text_value = str(raw_value).strip()
        if not text_value:
            continue
        subtitle_components.append(text_value)
        subtitle_badges.append(f"<span>{html.escape(label)}: {html.escape(text_value)}</span>")

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
        value = row.get(field)
        if value in (None, "") or (isinstance(value, float) and pd.isna(value)):
            continue
        title_components.append(str(value))

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
        f'<a class="ai-card-link" href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">View Listing</a>'
        if isinstance(url, str) and url.strip()
        else ""
    )

    odo_display = format_listing_odometer(row.get("odometer_reading"), row.get("odometer_unit"))
    header_html = f"""
    <div class="ai-card-header">
        <div class="ai-card-title-group">
            <div class="ai-card-title">{title_text}</div>
            {subtitle_html}
        </div>
        <div class="ai-card-metric">
            <div class="ai-card-metric-label">Odometer</div>
            <div class="ai-card-metric-value">{odo_display}</div>
            {link_html}
        </div>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)

def render_listing_metrics(row: pd.Series) -> None:
    col1, col2, col3 = st.columns(3)

    price_value = row.get("current_price")
    price_text = "--"
    if price_value not in (None, "") and not (isinstance(price_value, float) and pd.isna(price_value)):
        price_text = format_price_value(price_value)

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

    bids_value = row.get("bids")
    bids_text = "--"
    if bids_value not in (None, "") and not (isinstance(bids_value, float) and pd.isna(bids_value)):
        try:
            bids_text = f"{int(float(str(bids_value).replace(',', '').strip())):,}"
        except Exception:
            bids_text = str(bids_value)

    col1.metric("Current Price", price_text)
    col2.metric("Time Remaining", time_text)
    col3.metric("Bids", bids_text)


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
    seen: set[tuple] = set()
    for source_key in ("historical_matches_rows", "historical_close_matches_rows"):
        source_rows = _normalise_match_rows(row.get(source_key))
        if not source_rows:
            continue
        for entry in source_rows:
            entry_key = tuple(sorted(entry.items()))
            if entry_key in seen:
                continue
            seen.add(entry_key)
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
    st.dataframe(styled_df, use_container_width=True)

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




def ensure_manual_defaults(url: str, row: pd.Series) -> None:
    estimate_key = f"manual_estimate_{url}"
    if estimate_key not in st.session_state:
        saved_estimate = row.get("manual_carsales_estimate") if isinstance(row, pd.Series) else None
        if isinstance(saved_estimate, float) and pd.isna(saved_estimate):
            saved_estimate = None
        if isinstance(saved_estimate, (int, float)):
            st.session_state[estimate_key] = format_price_value(saved_estimate)
        elif isinstance(saved_estimate, str) and saved_estimate.strip():
            st.session_state[estimate_key] = saved_estimate.strip()
        else:
            st.session_state[estimate_key] = ""

    instant_key = f"manual_instant_offer_{url}"
    if instant_key not in st.session_state:
        saved_instant = row.get("manual_instant_offer_estimate") if isinstance(row, pd.Series) else None
        if isinstance(saved_instant, float) and pd.isna(saved_instant):
            saved_instant = None
        if isinstance(saved_instant, (int, float)):
            st.session_state[instant_key] = format_price_value(saved_instant)
        elif isinstance(saved_instant, str) and saved_instant.strip():
            st.session_state[instant_key] = saved_instant.strip()
        else:
            st.session_state[instant_key] = ""

    recent_key = f"manual_recent_sales_{url}"
    if recent_key not in st.session_state:
        saved_recent = row.get("manual_recent_sales_30d") if isinstance(row, pd.Series) else None
        if isinstance(saved_recent, float) and pd.isna(saved_recent):
            saved_recent = None
        if isinstance(saved_recent, (int, float)):
            st.session_state[recent_key] = str(int(saved_recent))
        elif isinstance(saved_recent, str) and saved_recent.strip():
            st.session_state[recent_key] = saved_recent.strip()
        else:
            st.session_state[recent_key] = ""


def render_manual_carsales_section(row: pd.Series) -> None:
    valuation_url = "https://www.carsales.com.au/car-valuations/"
    try:
        st.link_button("Open Carsales Valuation Tool", valuation_url)
    except AttributeError:
        st.markdown(f"[Open Carsales Valuation Tool]({valuation_url})", unsafe_allow_html=True)

    ensure_manual_defaults(row["url"], row)
    estimate_key = f"manual_estimate_{row['url']}"
    instant_key = f"manual_instant_offer_{row['url']}"
    recent_key = f"manual_recent_sales_{row['url']}"
    raw_table_key = f"manual_carsales_table_{row['url']}"
    if raw_table_key not in st.session_state:
        existing_table = row.get("manual_carsales_table")
        if isinstance(existing_table, str) and existing_table.strip():
            st.session_state[raw_table_key] = existing_table.strip()
        else:
            st.session_state[raw_table_key] = ""

    form_key = f"manual_carsales_form_{row['url']}"
    submitted = False
    with st.form(form_key):
        input_cols = st.columns(3)
        with input_cols[0]:
            st.text_input(
                label="Instant offer estimate",
                key=instant_key,
                placeholder="$20,000 - $25,000",
            )
        with input_cols[1]:
            st.text_input(
                label="Sell on Carsales estimate",
                key=estimate_key,
                placeholder="$25,000 - $32,000",
            )
        with input_cols[2]:
            st.text_input(
                label="Similar cars sold (30 days)",
                key=recent_key,
                placeholder="3",
            )
        submitted = st.form_submit_button("Save Carsales Data")

    instant_input_raw = str(st.session_state.get(instant_key) or "").strip()
    sell_input_raw = str(st.session_state.get(estimate_key) or "").strip()
    recent_sales_input_raw = str(st.session_state.get(recent_key) or "").strip()

    instant_input_value = parse_currency(instant_input_raw)
    sell_input_value = parse_currency(sell_input_raw)
    recent_sales_input_value = parse_int(recent_sales_input_raw)

    stored_instant_raw = row.get("manual_instant_offer_estimate")
    stored_sell_raw = row.get("manual_carsales_estimate")
    stored_recent_raw = row.get("manual_recent_sales_30d")

    stored_instant_value = parse_currency(stored_instant_raw)
    stored_sell_value = parse_currency(stored_sell_raw)
    stored_recent_value = parse_int(stored_recent_raw)

    manual_count = parse_int(row.get("manual_carsales_count"))
    manual_min = parse_currency(row.get("manual_carsales_min"))
    manual_max = parse_currency(row.get("manual_carsales_max"))
    manual_avg = parse_currency(row.get("manual_carsales_avg"))

    def parse_odometer_value(value: object) -> Optional[float]:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text_value = str(value).lower().replace("km", "").replace(",", "").strip()
        if not text_value:
            return None
        try:
            return float(text_value)
        except ValueError:
            return None

    manual_avg_odo_val = parse_odometer_value(row.get("manual_carsales_avg_odometer"))
    if manual_avg_odo_val is not None:
        manual_avg_odo_display = f"{int(round(manual_avg_odo_val)):,} km"
    else:
        raw_avg_odo = row.get("manual_carsales_avg_odometer")
        manual_avg_odo_display = raw_avg_odo if isinstance(raw_avg_odo, str) and raw_avg_odo.strip() else None

    instant_display_raw = instant_input_raw or (stored_instant_raw if isinstance(stored_instant_raw, str) else "")
    if not instant_display_raw and stored_instant_value is not None:
        instant_display_raw = format_price_value(stored_instant_value)

    sell_display_raw = sell_input_raw or (stored_sell_raw if isinstance(stored_sell_raw, str) else "")
    if not sell_display_raw and stored_sell_value is not None:
        sell_display_raw = format_price_value(stored_sell_value)

    recent_display_value = recent_sales_input_raw or (
        str(int(stored_recent_value)) if stored_recent_value is not None else ""
    )

    metrics: list[tuple[str, str]] = []
    if instant_display_raw:
        metrics.append(("Instant offer", instant_display_raw))
    if sell_display_raw:
        metrics.append(("Sell on Carsales", sell_display_raw))
    if recent_display_value:
        metrics.append(("Sales (30d)", recent_display_value))
    if manual_avg is not None:
        metrics.append(("Avg price", format_price_value(manual_avg)))
    if manual_min is not None:
        metrics.append(("Min price", format_price_value(manual_min)))
    if manual_max is not None:
        metrics.append(("Max price", format_price_value(manual_max)))
    if manual_avg_odo_display:
        metrics.append(("Avg odometer", manual_avg_odo_display))

    if metrics:
        cols = st.columns(len(metrics))
        for col, (label, value) in zip(cols, metrics):
            col.metric(label, value)
        if manual_count is not None:
            st.caption(f"Listings counted: {manual_count}")
        elif row.get("manual_carsales_count"):
            st.caption(f"Listings counted: {row.get('manual_carsales_count')}")
    else:
        st.caption("No Carsales pricing data saved yet. Enter estimates above and save them when ready.")

    if submitted:
        if not sell_input_raw:
            st.session_state["ai_manual_status"] = ("error", "Enter a Carsales sell estimate before saving.")
            if isinstance(row.get("url"), str):
                st.session_state["ai_focus_url"] = row["url"]
            st.rerun()
        table_raw = st.session_state.get(raw_table_key) or row.get("manual_carsales_table") or ""
        update_manual_carsales_data(
            row["url"],
            manual_count,
            manual_min,
            manual_max,
            manual_avg,
            manual_avg_odo_val,
            table_raw if isinstance(table_raw, str) else "",
            sell_input_raw,
            instant_input_raw,
            recent_sales_input_value,
        )
        if isinstance(row.get("url"), str):
            st.session_state["ai_focus_url"] = row["url"]
        st.session_state["ai_manual_status"] = ("success", "Carsales data saved.")
        refresh_ai_cache()
        st.rerun()


def refresh_ai_cache() -> None:
    st.session_state.ai_listing_cache = load_ai_cached_results()


if "ai_listing_cache" not in st.session_state:
    st.session_state.ai_listing_cache = load_ai_cached_results()

if "ai_refresh_status" in st.session_state:
    level, message = st.session_state.pop("ai_refresh_status")
    notifier = getattr(st, level, st.info)
    notifier(message)

if "ai_manual_status" in st.session_state:
    level, message = st.session_state.pop("ai_manual_status")
    notifier = getattr(st, level, st.info)
    notifier(message)

manual_lookup_df = st.session_state.ai_listing_cache
if not manual_lookup_df.empty:
    lookup = manual_lookup_df.set_index("url")
    for manual_column in MANUAL_COLS:
        if manual_column in lookup.columns:
            comparison_df[manual_column] = comparison_df["url"].map(lookup[manual_column])
comparison_df = ensure_columns(comparison_df, MANUAL_COLS)

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


def render_ai_result(url: str) -> None:
    cache_df = st.session_state.ai_listing_cache
    if cache_df.empty or url not in cache_df["url"].values:
        st.caption("No AI Carsales analysis yet.")
        return

    record = cache_df[cache_df["url"] == url].iloc[0]
    st.markdown("**AI Carsales Check**")
    timestamp = record.get("analysis_timestamp")
    if pd.notna(timestamp):
        st.caption(f"Last updated: {timestamp}")

    col1, col2, col3 = st.columns(3)
    col1.metric("Carsales Estimate", record.get("carsales_price_estimate", "—"))
    col2.metric("Recommended Max Bid", record.get("recommended_max_bid", "—"))
    col3.metric("Expected Profit", record.get("expected_profit", "—"))

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
        st.write(" • ".join(info_line_parts))

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
] + MANUAL_COLS)
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
] + MANUAL_COLS)
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
] + MANUAL_COLS)

tabs = st.tabs(["Under Historical Pricing", "No Historical Data"])

with tabs[0]:
    if underpriced_df.empty:
        st.info("No listings meet the current filters.")
    else:
        for _, row in underpriced_df.iterrows():
            anchor_id = build_anchor_id(row.get("url"))
            st.markdown(f"<div id='{anchor_id}'></div>", unsafe_allow_html=True)
            with st.container():
                st.markdown("---")
                render_listing_header(row)
                st.markdown("### Auction Data")
                render_listing_metrics(row)
                render_closest_matches_section(row)

                st.markdown("### Carsales Data")
                render_manual_carsales_section(row)

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
                        render_ai_result(row["url"])
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
                        render_ai_result(row["url"])
                        rendered = True

                if not rendered:
                    render_ai_result(row["url"])

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
                st.markdown("---")
                render_listing_header(row)
                st.markdown("### Auction Data")
                render_listing_metrics(row)
                render_closest_matches_section(row)

                st.markdown("### Carsales Data")
                render_manual_carsales_section(row)

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
                        render_ai_result(row["url"])
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
                        render_ai_result(row["url"])
                        rendered = True

                if not rendered:
                    render_ai_result(row["url"])

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

