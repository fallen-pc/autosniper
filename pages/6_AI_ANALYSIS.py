import asyncio

import html

import json

import os

import re

import textwrap

import time

from typing import Any, Callable, Iterable, Mapping, Optional

from urllib.parse import quote_plus



import pandas as pd

import streamlit as st

import streamlit.components.v1 as components


try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore[assignment]


# Configure OpenAI client (optional; required for running AI analysis).
api_key = os.getenv("OPENAI_API_KEY")
client = None
if api_key and OpenAI is not None:
    client = OpenAI(api_key=api_key)
elif not api_key:
    st.warning("OpenAI API key not set; AI analysis actions will be disabled.")
else:
    st.warning("OpenAI client unavailable; install the openai package to unlock AI analysis.")


from scripts.ai_price_analysis import (

    compare_active_to_history,

    load_active_listings_within_hours,

    load_historical_sales,

    _to_int_or_none,

)

from scripts.ai_listing_valuation import (

    load_cached_results as load_ai_cached_results,

    run_ai_listing_analysis,

    update_manual_carsales_data,

)

from scripts.vehicle_updates import coerce_price
from scripts.update_bids import update_bids

from shared.data_loader import dataset_path, ensure_datasets_available
from shared.filter_controls import (
    apply_vehicle_filters,
    describe_time_selection,
    render_time_filter,
    render_vehicle_filter_toggles,
)
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


st.sidebar.header("Time Window")

time_label, time_bounds = render_time_filter(
    container=st.sidebar,
    label="Show listings finishing within",
    default_option="< 24h",
)
lower_bound, upper_bound = time_bounds
selected_min_hours = 0.0 if lower_bound is None else lower_bound
selected_max_hours = upper_bound

time_window_text = describe_time_selection(time_label)
time_window_refresh_text = f"listings finishing within {time_window_text}"

st.caption(
    f"Active listings finishing within {time_window_text} compared with historical sales data."
)





@st.cache_data(ttl=300)

def get_active_listings(min_hours: float, max_hours: float, file_version: float) -> pd.DataFrame:

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

    active_path = dataset_path("active_vehicle_details.csv")
    active_version = active_path.stat().st_mtime if active_path.exists() else time.time()

    active_df = get_active_listings(min_hours, max_hours, active_version)

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

manual_columns = [
    "manual_carsales_min",
    "manual_carsales_max",
    "manual_carsales_avg",
    "manual_carsales_sold_30d",
    "manual_recent_sales_30d",
    "manual_carsales_count",
    "manual_carsales_table",
    "manual_carsales_estimate",
    "carsales_skipped",
]

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
    *manual_columns,
]
available_columns = [column for column in valuation_columns if column in valuations_cache.columns]
if available_columns:
    valuations_subset = valuations_cache[["url", *available_columns]].copy()
    comparison_df = comparison_df.merge(valuations_subset, on="url", how="left", suffixes=("", "_ai"))
    for column in manual_columns + [
        "analysis_timestamp",
        "carsales_price_estimate",
        "carsales_price_range",
        "recommended_max_bid",
        "expected_profit",
        "profit_margin_percent",
        "score_out_of_10",
        "confidence_notes",
    ]:
        ai_column = f"{column}_ai"
        if ai_column in comparison_df.columns:
            comparison_df[column] = comparison_df[column].fillna(comparison_df[ai_column])
            comparison_df.drop(columns=[ai_column], inplace=True)

# Bring in valuations that aren't in the active comparison (e.g., cached/manual entries only).
if not valuations_cache.empty:
    comparison_urls = set(comparison_df["url"].astype(str).str.strip())
    valuation_urls = set(valuations_cache["url"].astype(str).str.strip())
    missing_urls = valuation_urls - comparison_urls
    if missing_urls:
        extras = valuations_cache[valuations_cache["url"].astype(str).str.strip().isin(missing_urls)].copy()
        # Minimal fields to display; fill placeholders for absent active data.
        extras["status"] = "manual_only"
        extras["hours_remaining"] = pd.NA
        # Populate title fields from any available columns.
        extras_year = extras["year"] if "year" in extras else extras.get("Year")
        extras_make = extras["make"] if "make" in extras else extras.get("Make")
        extras_model = extras["model"] if "model" in extras else extras.get("Model")
        extras_variant = extras["variant"] if "variant" in extras else extras.get("Variant")

        extras["year"] = extras_year if extras_year is not None else pd.Series([pd.NA] * len(extras))
        extras["make"] = extras_make if extras_make is not None else pd.Series([pd.NA] * len(extras))
        extras["model"] = extras_model if extras_model is not None else pd.Series([pd.NA] * len(extras))
        extras["variant"] = extras_variant if extras_variant is not None else pd.Series([pd.NA] * len(extras))
        # Drop entries without basic identity fields.
        extras = extras[extras["make"].notna() & extras["model"].notna()]
        extras["make_norm"] = extras["make"].astype(str).str.lower().str.strip()
        extras["model_norm"] = extras["model"].astype(str).str.lower().str.strip()
        extras["variant_norm"] = extras["variant"].astype(str).str.lower().str.strip() if "variant" in extras else pd.NA
        extras["year_int"] = extras["year"].apply(_to_int_or_none) if "year" in extras else pd.NA
        comparison_df = pd.concat([comparison_df, extras], ignore_index=True, sort=False)

# Enforce presence of manual Carsales fields and filter out rows missing them.
for manual_column in ("manual_carsales_min",):
    if manual_column not in comparison_df.columns:
        comparison_df[manual_column] = None
if "carsales_skipped" not in comparison_df.columns:
    comparison_df["carsales_skipped"] = False

comparison_df["_manual_min_numeric"] = comparison_df["manual_carsales_min"].apply(coerce_price)
comparison_df["_has_manual_carsales"] = (
    comparison_df["_manual_min_numeric"].notna()
    & (comparison_df["_manual_min_numeric"] > 0)
    & ~comparison_df["carsales_skipped"].fillna(False).astype(bool)
)
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
    "manual_carsales_avg",
    "manual_carsales_sold_30d",
    "manual_recent_sales_30d",
    "manual_carsales_count",
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

# Recompute manual flags and optionally filter to manual-only.
comparison_df["_manual_min_numeric"] = comparison_df["manual_carsales_min"].apply(coerce_price)
comparison_df["_has_manual_carsales"] = (
    comparison_df["_manual_min_numeric"].notna()
    & (comparison_df["_manual_min_numeric"] > 0)
    & ~comparison_df["carsales_skipped"].fillna(False).astype(bool)
)
show_only_manual = st.sidebar.checkbox("Show only listings with manual Carsales", value=True)
if show_only_manual:
    comparison_df = comparison_df[comparison_df["_has_manual_carsales"]].copy()

if st.button("Run full AI analysis"):
    if client is None:
        st.error("OpenAI API key not set; cannot run AI analysis.")
    else:
        errors: list[str] = []
        with st.spinner("Running AI pricing across listings..."):
            for _, row in comparison_df.iterrows():
                result = run_ai_listing_analysis(row)
                if result.get("error"):
                    errors.append(str(row.get("url", "unknown")))
        refresh_ai_cache()
        if errors:
            st.warning(f"AI analysis completed with {len(errors)} errors.")
        else:
            st.success("AI analysis refreshed for all listings.")
        st.rerun()

focus_url = st.session_state.pop("ai_focus_url", None)

# Vehicle-level sidebar filters aligned with Active Listings view.

st.sidebar.markdown("### Vehicle Filters")
vehicle_toggles = render_vehicle_filter_toggles(container=st.sidebar, key_prefix="ai_")
comparison_df = apply_vehicle_filters(comparison_df, vehicle_toggles)



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

            if text.lower() in {"nan", "none", "n/a"}:

                return "—"

            if not text:

                return "—"

            if text.startswith("$"):

                text = text.replace("$", "").replace(",", "")

            return f"${float(text):,.0f}"

        return f"${float(value):,.0f}"

    except Exception:  # noqa: BLE001

        return str(value)


def format_price_range(min_val: object, max_val: object) -> Optional[str]:

    min_price = coerce_price(min_val)
    max_price = coerce_price(max_val)

    if min_price is None and (max_price is None or (isinstance(max_price, float) and pd.isna(max_price))):
        return None

    if max_price is None or (isinstance(max_price, float) and pd.isna(max_price)):
        return format_price_value(min_price)

    return f"{format_price_value(min_price)} - {format_price_value(max_price)}"





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

    subtitle_badges: list[str] = []

    manual_min = coerce_price(row.get("manual_carsales_min"))
    manual_max = coerce_price(row.get("manual_carsales_max"))
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
    if manual_min and manual_max and not manual_skipped:
        subtitle_badges.append(
            "<span class='ai-card-condition-badge' style='background: rgba(94,230,167,.18);"
            "border: 1px solid rgba(94,230,167,.45); color: #5EE6A7;'>"
            "✅ Carsales Estimate Complete</span>"
        )

    variant_text = _clean_text(row.get("variant"))

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

    card_body = ""

    inner_html = f"""
    <div class="ai-card-header">
        <div class="ai-card-title-group">
            <div class="ai-card-title">{title_text}</div>
            {subtitle_html}
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


def safe_display(value: object, default: str = "--") -> str:
    if value is None:
        return default
    if isinstance(value, float) and pd.isna(value):
        return default
    text = str(value).strip()
    return text or default


def render_spec_list(
    row: pd.Series,
    fields: Iterable[tuple[str, str] | tuple[str, str, Callable[..., str]]],
) -> str:
    entries: list[tuple[str, str]] = []

    for field in fields:
        if len(field) == 2:
            label, key = field
            formatter = None
        else:
            label, key, formatter = field  # type: ignore[misc]

        raw_value = row.get(key)
        display_value = safe_display(raw_value)

        if formatter:
            try:
                display_value = formatter(raw_value, row)  # type: ignore[arg-type]
            except TypeError:
                display_value = formatter(raw_value)  # type: ignore[misc]
            except Exception:
                display_value = safe_display(raw_value)

        if display_value in ("--", "N/A", ""):
            continue

        entries.append((label, str(display_value)))

    if not entries:
        return ""

    items_html = "".join(
        f"<div class='ai-spec-item'><div class='ai-spec-label'>{html.escape(label)}</div>"
        f"<div class='ai-spec-value'>{html.escape(value)}</div></div>"
        for label, value in entries
    )
    return f"<div class='ai-spec-list'>{items_html}</div>"


def format_condition_entries(row: pd.Series) -> tuple[str | None, list[tuple[str, str]], list[str]]:
    summary = safe_display(row.get("general_condition"), "").strip()
    if not summary or summary == "--":
        summary = None

    feature_entries: list[str] = []
    features_raw = row.get("features_list")
    if isinstance(features_raw, str):
        for chunk in re.split(r"[\n;,•]+", features_raw):
            cleaned = chunk.strip(" -")
            if cleaned:
                feature_entries.append(cleaned)

    badges: list[tuple[str, str]] = []
    for column in CONDITION_COLUMNS:
        if column == "general_condition":
            continue
        value = safe_display(row.get(column)).strip()
        if not value or value == "--":
            continue
        label = column.replace("_", " ").title()
        badges.append((label, value))

    return summary, badges, feature_entries


def render_condition_column(row: pd.Series) -> str:
    summary, badges, features = format_condition_entries(row)
    segments: list[str] = []

    if summary:
        segments.append(f"<p class='ai-condition-summary'>{html.escape(summary)}</p>")

    if badges:
        badges_html = "".join(
            f"<span class='ai-card-condition-badge'><strong>{html.escape(label)}:</strong> {html.escape(value)}</span>"
            for label, value in badges
        )
        segments.append(f"<div class='ai-card-condition-badges'>{badges_html}</div>")

    if not segments:
        return ""

    return "<div class='ai-condition-column'>" + "".join(segments) + "</div>"


def extract_best_match_entry(row: pd.Series) -> tuple[dict[str, object] | None, dict[str, float] | None]:
    try:
        matches, summaries, _ = get_closest_matches(row)
    except Exception:
        return None, None

    best_match = matches[0] if matches else None
    summary_entry = summaries[0] if summaries else None
    return best_match, summary_entry


def render_vehicle_summary(row: pd.Series) -> None:
    st.markdown("### Vehicle Snapshot")
    url = row.get("url")
    view_link = ""
    if isinstance(url, str) and url.strip():
        view_link = (
            f'<a class="ai-card-link-button ai-snapshot-link" href="{html.escape(url)}" '
            'target="_blank" rel="noopener noreferrer">View Listing</a>'
        )
    spec_fields = [
        ("Current Price", "current_price", lambda _value, current_row: _format_price_or_dash(current_row)),
        ("Time Remaining", "time_remaining_or_date_sold", lambda _value, current_row: _format_time_remaining(current_row)),
        ("Bids", "bids"),
        ("Location", "location"),
        ("Odometer", "odometer_reading", lambda value, current_row: format_listing_odometer(value, current_row.get("odometer_unit"))),
        ("Transmission", "transmission"),
    ]

    spec_html = render_spec_list(row, spec_fields)
    summary, badges, _ = format_condition_entries(row)

    if spec_html:
        actions_html = f"<div class='ai-spec-actions'>{view_link}</div>" if view_link else ""
        st.markdown(f"<div class='ai-spec-wrapper'>{actions_html}{spec_html}</div>", unsafe_allow_html=True)
    else:
        if view_link:
            st.markdown(f"<div class='ai-spec-actions'>{view_link}</div>", unsafe_allow_html=True)
        st.caption("No auction metrics captured yet.")

    if summary:
        st.markdown(f"<div class='ai-condition-summary'>{html.escape(summary)}</div>", unsafe_allow_html=True)

    if badges:
        badge_html = "".join(
            f"<span class='ai-card-condition-badge'><strong>{html.escape(label)}:</strong> {html.escape(value)}</span>"
            for label, value in badges
        )
        st.markdown(f"<div class='ai-card-condition-badges'>{badge_html}</div>", unsafe_allow_html=True)


def _format_time_remaining(row: pd.Series) -> str:
    value = row.get("time_remaining_or_date_sold")
    if value not in (None, "") and not (isinstance(value, float) and pd.isna(value)):
        text = str(value).strip()
        if text:
            return text
    hours_remaining = row.get("hours_remaining")
    if hours_remaining not in (None, "") and not (isinstance(hours_remaining, float) and pd.isna(hours_remaining)):
        try:
            return f"{float(hours_remaining):.1f}h"
        except Exception:
            return safe_display(hours_remaining)
    return "--"


def _format_price_or_dash(row: pd.Series) -> str:
    raw_price = _first_non_empty(row.get("current_price"), row.get("price"))
    if raw_price in (None, "", "None") or (isinstance(raw_price, float) and pd.isna(raw_price)):
        return "--"
    return format_price_value(raw_price)


def render_comparison_section(row: pd.Series) -> None:
    st.markdown("### Auction vs History")

    best_match, summary_entry = extract_best_match_entry(row)

    def _match_value(entry: dict[str, Any] | None, *keys: str) -> Any:
        if not entry:
            return None
        for key in keys:
            if key in entry and entry[key] not in (None, "", " "):
                value = entry[key]
                if isinstance(value, float) and pd.isna(value):
                    continue
                return value
        return None

    def _pull_value(data: Mapping[str, Any] | pd.Series | None, key: str) -> Any:
        if data is None:
            return None
        if isinstance(data, Mapping):
            return data.get(key)
        if isinstance(data, pd.Series):
            return data.get(key)
        return None

    def _format_registration(data: Mapping[str, Any] | pd.Series | None) -> str:
        if data is None:
            return "Unregistered"
        state = _first_non_empty(
            _pull_value(data, "rego_state"),
            _pull_value(data, "Registration State"),
            _pull_value(data, "rego_state_clean"),
        )
        expiry = _first_non_empty(
            _pull_value(data, "rego_expiry"),
            _pull_value(data, "Registration Expiry Date"),
        )
        if state and expiry:
            return f"{state} (exp {expiry})"
        if state:
            return str(state)
        return "Unregistered"

    def _format_condition_text(value: object) -> str:
        text = safe_display(value)
        if text in ("--", "", "N/A"):
            return "—"
        return textwrap.shorten(text, width=140, placeholder="…")

    current_odometer = format_listing_odometer(row.get("odometer_reading"), row.get("odometer_unit"))
    match_odometer = format_listing_odometer(
        _match_value(best_match, "odometer_reading", "Odometer"),
        _match_value(best_match, "odometer_unit", "Odometer Unit"),
    )
    current_location = safe_display(row.get("location"))
    match_location = safe_display(_match_value(best_match, "location", "Location"))
    current_registered = _format_registration(row)
    match_registered = _format_registration(best_match)
    current_condition = _format_condition_text(row.get("general_condition"))
    summary_condition_value = None
    if summary_entry:
        summary_condition_value = summary_entry.get("Condition") or summary_entry.get("condition")
    match_condition = _format_condition_text(
        _match_value(
            best_match,
            "general_condition",
            "General Condition",
            "condition",
            "Condition",
        )
        or summary_condition_value
    )

    if not best_match:
        st.caption("No comparable sale recorded yet.")
        render_closest_matches_section(row)
        return

    comparison_rows = [
        ("Odometer", current_odometer, match_odometer),
        ("Location", current_location, match_location),
        ("Registered", current_registered, match_registered),
        ("Condition Notes", current_condition, match_condition),
    ]
    table_rows = [
        "<div class='ai-comparison-table-row ai-comparison-table-header'>"
        "<div></div><div>Current Auction</div><div>Closest Historical Sale</div></div>"
    ]
    for label, current_value, match_value in comparison_rows:
        table_rows.append(
            "<div class='ai-comparison-table-row'>"
            f"<div class='ai-comparison-label'>{html.escape(label)}</div>"
            f"<div>{html.escape(current_value)}</div>"
            f"<div>{html.escape(match_value)}</div>"
            "</div>"
        )
    st.markdown(
        "<div class='ai-comparison-table'>" + "".join(table_rows) + "</div>",
        unsafe_allow_html=True,
    )

    current_price_metric = _format_price_or_dash(row)
    previous_price_metric = format_price_value(best_match.get("final_price_numeric"))
    current_odo_numeric = parse_odometer_value(row.get("odometer_numeric")) or parse_odometer_value(row.get("odometer_reading"))
    match_odo_numeric = parse_odometer_value(_match_value(best_match, "odometer_numeric", "Odometer", "odometer_reading"))
    odo_delta = "—"
    if current_odo_numeric is not None and match_odo_numeric is not None:
        diff_val = match_odo_numeric - current_odo_numeric
        direction = "higher" if diff_val > 0 else "lower"
        if diff_val == 0:
            direction = "same"
        odo_delta = f"{abs(diff_val):,.0f} km {direction}"
    stats_cols = st.columns(3)
    stats_cols[0].metric("Current Price", current_price_metric)
    stats_cols[1].metric("Previous Auction Price", previous_price_metric or "--")
    stats_cols[2].metric("Odometer Δ", odo_delta)

    render_closest_matches_section(row)


def render_carsales_section(row: pd.Series) -> None:
    st.markdown("### Carsales & Manual Research")
    manual_estimate = _first_non_empty(
        row.get("manual_carsales_estimate"),
        row.get("manual_carsales_avg"),
        format_price_range(row.get("manual_carsales_min"), row.get("manual_carsales_max")),
    )
    manual_range = format_price_range(row.get("manual_carsales_min"), row.get("manual_carsales_max"))
    manual_count = row.get("manual_carsales_count")
    manual_recent = row.get("manual_recent_sales_30d")

    stats = st.columns(3)
    stats[0].metric("Carsales Range", manual_range or "--")
    stats[1].metric("Carsales Estimate", format_price_value(manual_estimate) if manual_estimate else "--")
    stats[2].metric("Sold last 30d", safe_display(manual_recent))

    manual_table = row.get("manual_carsales_table")
    parsed_table = parse_markdown_table(manual_table) if isinstance(manual_table, str) else None
    if parsed_table is not None and not parsed_table.empty:
        st.dataframe(parsed_table, use_container_width=True, hide_index=True)
    else:
        st.caption("Add manual Carsales comparisons to see them here.")


def format_confidence_notes(notes: object) -> list[str]:
    if notes is None:
        return []
    if isinstance(notes, float) and pd.isna(notes):
        return []
    text = str(notes).strip()
    if not text:
        return []
    parts = [part.strip(" -") for part in re.split(r"[;\n•]+", text) if part.strip(" -")]
    return parts


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
            "general_condition": (
                entry.get("general_condition")
                or entry.get("General Condition")
                or entry.get("condition")
                or entry.get("Condition")
            ),
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









def refresh_ai_cache() -> None:

    st.session_state.ai_listing_cache = load_ai_cached_results()





if "ai_refresh_status" in st.session_state:

    level, message = st.session_state.pop("ai_refresh_status")

    notifier = getattr(st, level, st.info)

    notifier(message)



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
        "recent_sales_30d": listing_row.get("manual_recent_sales_30d"),
    }
    manual_clean = {key: value for key, value in manual_snapshot.items() if _value_has_data(value)}
    if manual_clean:
        snapshot["carsales_manual_snapshot"] = manual_clean
    return {key: value for key, value in snapshot.items() if _value_has_data(value)}


def render_ai_result(url: str, listing_row: Optional[pd.Series] = None) -> None:
    cache_df = st.session_state.ai_listing_cache
    has_record = not cache_df.empty and url in cache_df["url"].values
    if not has_record:
        st.caption("Run the AI Carsales check to populate the verdict.")
        return

    record = cache_df[cache_df["url"] == url].iloc[0]
    record_data = record.to_dict()

    ai_estimate = format_price_value(record_data.get("carsales_price_estimate"))
    max_bid = format_price_value(record_data.get("recommended_max_bid"))
    expected_profit = format_price_value(record_data.get("expected_profit"))
    score = safe_display(record_data.get("score_out_of_10"))
    margin = safe_display(record_data.get("profit_margin_percent"))
    timestamp = safe_display(record_data.get("analysis_timestamp"))

    metrics = st.columns(4)
    metrics[0].metric("AI Carsales Estimate", ai_estimate)
    metrics[1].metric("Recommended Max Bid", max_bid)
    metrics[2].metric("Expected Profit", expected_profit)
    metrics[3].metric("Score /10", score or "--")

    st.caption(
        f"Profit margin: {margin or '--'} | Last analysed: {timestamp or '—'}"
    )

    note_entries = format_confidence_notes(record_data.get("confidence_notes"))
    if note_entries:
        st.markdown("**AI Notes**")
        for entry in note_entries:
            st.markdown(f"- {entry}")

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



matched_df = comparison_df[comparison_df["_has_displayable_history"]].copy()

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

                render_vehicle_summary(row)
                render_comparison_section(row)
                render_carsales_section(row)
                st.markdown("### Verdict")

                action_col, rerun_col, full_col = st.columns([1, 1, 1])

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

                render_vehicle_summary(row)
                render_comparison_section(row)
                render_carsales_section(row)
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
