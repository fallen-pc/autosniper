import html
import urllib.parse
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from scripts.ai_price_analysis import _extract_hours_remaining
from scripts.vehicle_updates import coerce_price, update_vehicle_estimates
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.filter_controls import (
    apply_vehicle_filters,
    render_time_filter,
    render_vehicle_filter_toggles,
)
from shared.styling import clean_html, inject_global_styles, page_intro


st.set_page_config(
    page_title="Manual Carsales Estimate Input",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_global_styles()

st.markdown(
    "<style>[data-testid='stSidebar']{display:block !important;}</style>",
    unsafe_allow_html=True,
)
st.markdown(
    clean_html(
        """
        <style>
        .manual-card {
            border: 1px solid var(--autosniper-border);
            background: var(--autosniper-panel);
            border-radius: 16px;
            padding: 1.1rem 1.25rem;
            box-shadow: 0 10px 20px rgba(0,0,0,0.24);
            margin-bottom: 1rem;
        }
        .manual-title {
            display: block;
            font-size: 1.25rem;
            font-weight: 800;
            color: var(--autosniper-primary);
            letter-spacing: -0.01em;
        }
        .manual-meta {
            color: var(--autosniper-muted);
            font-size: 0.95rem;
            margin-top: 0.15rem;
            margin-bottom: 0.35rem;
        }
        [data-testid="stSidebar"] .stSelectbox,
        [data-testid="stSidebar"] .stNumberInput,
        [data-testid="stSidebar"] .stTextInput {
            margin-bottom: 0.65rem;
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

page_intro(
    "MANUAL CARSALES ESTIMATES",
    "Enter Carsales resale ranges and recent sales counts. Saved rows disappear from the list because completed items are filtered out.",
)
st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Entry format</div>
            <div class="section-subtitle">
                Use <strong>min - max</strong> for price ranges (e.g. <code>$15,000 - $18,000</code>).
                The dashboard automatically sets the average to the midpoint. Enter the <strong>sold last 30 days</strong> count as a whole number.
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)


EXCLUDED_STATUSES = {"sold", "closed", "canceled", "cancelled", "referred"}


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in (
        "manual_carsales_min",
        "manual_carsales_max",
        "manual_carsales_sold_30d",
        "manual_carsales_avg",
        "manual_recent_sales_30d",
        "manual_carsales_count",
        "manual_carsales_table",
        "manual_carsales_estimate",
        "carsales_skipped",
    ):
        if col not in df.columns:
            df[col] = None
    df["carsales_skipped"] = df["carsales_skipped"].fillna(False)
    return df


def _is_blank(value: Any) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    text = str(value).strip()
    if not text:
        return True
    try:
        return float(text.replace("$", "").replace(",", "")) == 0
    except Exception:
        return False


@st.cache_data(ttl=300)
def _load_vehicle_table() -> pd.DataFrame:
    source_files = ["active_vehicle_details.csv", "vehicle_static_details.csv"]
    missing = ensure_datasets_available(source_files)
    if len(missing) == len(source_files):
        st.error("Missing dataset: active_vehicle_details.csv")
        st.stop()

    using_active = "active_vehicle_details.csv" not in missing
    source_path = dataset_path("active_vehicle_details.csv") if using_active else dataset_path("vehicle_static_details.csv")
    if not using_active:
        st.info("Active listings dataset missing; falling back to vehicle_static_details.csv.")
    path = source_path
    df = pd.read_csv(path)
    df = _ensure_columns(df)

    ai_cache_path = dataset_path("ai_listing_valuations.csv")
    manual_sync_columns = [
        "manual_carsales_min",
        "manual_carsales_max",
        "manual_carsales_avg",
        "manual_carsales_sold_30d",
        "manual_recent_sales_30d",
        "manual_carsales_count",
        "manual_carsales_estimate",
        "manual_carsales_table",
    ]
    if ai_cache_path.exists():
        ai_df = pd.read_csv(ai_cache_path)
        if "url" in ai_df.columns:
            subset_cols = ["url"] + [col for col in manual_sync_columns + ["carsales_skipped"] if col in ai_df.columns]
            ai_subset = ai_df[subset_cols].copy()
            df = df.merge(ai_subset, on="url", how="left", suffixes=("", "_ai"))
            for column in manual_sync_columns:
                ai_column = f"{column}_ai"
                if ai_column in df.columns:
                    mask = df[column].apply(_is_blank)
                    df.loc[mask, column] = df.loc[mask, ai_column]
                    df.drop(columns=[ai_column], inplace=True)
            ai_skip = "carsales_skipped_ai"
            if ai_skip in df.columns:
                df["carsales_skipped"] = df["carsales_skipped"].fillna(df[ai_skip])
                df.drop(columns=[ai_skip], inplace=True)

    df["status"] = df.get("status", "").astype(str).str.strip().str.lower()

    if "hours_remaining" not in df.columns:
        df["hours_remaining"] = df.get("time_remaining_or_date_sold", "").apply(_extract_hours_remaining)

    if "auction_end_time" in df.columns:
        df["auction_end_time_parsed"] = pd.to_datetime(df["auction_end_time"], errors="coerce")
    else:
        df["auction_end_time_parsed"] = pd.NaT

    df["location_clean"] = (
        df.get("location", pd.Series([None] * len(df), index=df.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .replace({"nan": "", "None": ""})
    )

    return df


def _carsales_search_url(row: pd.Series) -> str:
    parts = [str(row.get("year", "")).strip(), row.get("make", ""), row.get("model", ""), row.get("variant", "")]
    slug = "-".join([str(p).strip() for p in parts if p not in (None, "")])
    slug = "-".join(slug.split())
    encoded = urllib.parse.quote_plus(slug.lower())
    return f"https://www.carsales.com.au/cars/{encoded}"


def _format_odometer(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    try:
        return f"{int(float(str(value).replace(',', '').strip())):,} km"
    except Exception:
        text = str(value).strip()
        return f"{text} km" if text else "N/A"


def _format_range_text(min_val: Any, max_val: Any) -> str:
    if min_val is None and max_val is None:
        return ""
    min_txt = f"${float(min_val):,.0f}" if min_val is not None and not pd.isna(min_val) else ""
    max_txt = f"${float(max_val):,.0f}" if max_val is not None and not pd.isna(max_val) else ""
    if min_txt and max_txt:
        return f"{min_txt} - {max_txt}"
    return min_txt or max_txt


def _parse_range_text(raw: Any) -> tuple[Optional[float], Optional[float]]:
    """Accept '12000-15000' or '$12k - $15k' and return (min, max)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None
    normalized = text.lower().replace("to", "-").replace("–", "-").replace("—", "-")
    parts = [p for p in normalized.split("-") if p.strip()]
    values: list[float] = []
    for part in parts:
        val = coerce_price(part)
        if val is not None:
            values.append(val)
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], None
    return values[0], values[1]


def _format_price(value: Any) -> str:
    parsed = coerce_price(value)
    if parsed is None:
        return "N/A"
    return f"${parsed:,.0f}"


df = _load_vehicle_table()

# Filters
st.sidebar.markdown("### Filters")
time_label, time_bounds = render_time_filter(
    container=st.sidebar,
    label="Time remaining",
    default_option="< 24h",
)
vehicle_toggles = render_vehicle_filter_toggles(container=st.sidebar)
df = apply_vehicle_filters(df, vehicle_toggles)

# Base filtering
missing_manual_mask = df["manual_carsales_min"].apply(_is_blank)
status_mask = ~df["status"].isin(EXCLUDED_STATUSES)
skip_mask = ~df["carsales_skipped"].fillna(False).astype(bool)
hours_mask = pd.Series([True] * len(df))
lower_bound, upper_bound = time_bounds
if lower_bound is not None or upper_bound is not None:
    hours_mask = df["hours_remaining"].apply(
        lambda val: (
            (lower_bound is None or (val is not None and val >= lower_bound))
            and (upper_bound is None or (val is not None and val < upper_bound))
        )
    )

filtered = df[missing_manual_mask & status_mask & skip_mask & hours_mask].copy()

if filtered.empty:
    st.info("No vehicles need manual Carsales estimates right now.")
    st.stop()

# Sort by auction end time (when available) or hours remaining.
filtered["sort_key"] = filtered.apply(
    lambda row: row["auction_end_time_parsed"]
    if pd.notna(row["auction_end_time_parsed"])
    else row.get("hours_remaining", None),
    axis=1,
)
filtered = filtered.sort_values(by="sort_key", kind="mergesort")

filtered["carsales_search"] = filtered.apply(_carsales_search_url, axis=1)
filtered["odometer_display"] = filtered["odometer_reading"].apply(_format_odometer)

st.markdown("Enter ranges and counts below, then click **Save** for each row.")
st.divider()

st.caption(f"Showing {len(filtered)} vehicles needing manual entries.")


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))
    except Exception:
        return None


for _, row in filtered.iterrows():
    url = str(row.get("url", "")).strip()
    parts = [row.get("year"), row.get("make"), row.get("model"), row.get("variant")]
    safe_parts = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, float) and pd.isna(part):
            continue
        if isinstance(part, pd._libs.missing.NAType):
            continue
        text = str(part).strip()
        if not text:
            continue
        safe_parts.append(text)
    title = " ".join(safe_parts)

    with st.form(key=f"manual_form_{url}"):
        st.markdown("<div class='manual-card'>", unsafe_allow_html=True)
        header_col, meta_col = st.columns([3, 2])
        header_col.markdown(f"<span class='manual-title'>{html.escape(title)}</span>", unsafe_allow_html=True)
        header_col.markdown(
            f"<div class='manual-meta'>{row.get('location_clean', 'Location: N/A') or 'Location: N/A'}</div>",
            unsafe_allow_html=True,
        )
        meta_col.write(row.get("odometer_display", "N/A"))
        meta_col.caption(f"{row.get('transmission', 'N/A')} | {row.get('fuel_type', 'N/A')}")
        price_display = _format_price(row.get("price") or row.get("current_price"))
        meta_col.caption(f"Current price: {price_display}")
        listing_link = row.get("url") or row.get("carsales_search", "")
        link_label = "Open listing" if row.get("url") else "Carsales search"
        meta_col.markdown(f"[{link_label}]({listing_link})", unsafe_allow_html=False)

        resale_default = _format_range_text(row.get("manual_carsales_min"), row.get("manual_carsales_max"))
        sold_default = _safe_int(row.get("manual_carsales_sold_30d")) or 0

        resale_col, sold_col = st.columns([3, 1])
        resale_input = resale_col.text_input(
            "Carsales resale (min - max)",
            value=resale_default,
            placeholder="$15,000 - $18,000",
        )
        sold_input = sold_col.number_input(
            "Sold last 30d",
            min_value=0,
            step=1,
            value=sold_default,
            help="Count of similar vehicles sold on Carsales in the last 30 days.",
        )

        action_col1, action_col2, _ = st.columns([1, 1, 3])
        save_clicked = action_col1.form_submit_button("Save")
        skip_clicked = action_col2.form_submit_button("Skip")

        if save_clicked:
            manual_min, manual_max = _parse_range_text(resale_input)
            if manual_min is None:
                st.error("Carsales resale range is required (min or min-max).")
                continue

            updated = update_vehicle_estimates(
                url,
                manual_min=manual_min,
                manual_max=manual_max,
                sold_last_30d=int(sold_input) if sold_input is not None else None,
                skipped=False,
            )
            if updated:
                st.success("Saved Carsales estimates.")
                _load_vehicle_table.clear()
                st.rerun()
            else:
                st.error("Unable to update this vehicle.")

        if skip_clicked:
            updated = update_vehicle_estimates(url, skipped=True)
            if updated:
                st.info("Skipped. You can revisit later by clearing the flag in CSV.")
                _load_vehicle_table.clear()
                st.rerun()
            else:
                st.error("Unable to skip this vehicle.")

        st.markdown("</div>", unsafe_allow_html=True)
