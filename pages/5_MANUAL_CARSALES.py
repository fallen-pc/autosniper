import html
import urllib.parse
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from scripts.ai_price_analysis import _extract_hours_remaining
from scripts.vehicle_updates import coerce_price, update_vehicle_estimates
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.styling import clean_html, display_banner, inject_global_styles


st.set_page_config(
    page_title="Manual Carsales Estimate Input",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_global_styles()
display_banner()
st.markdown(
    "<style>[data-testid='stSidebar']{display:block !important;}</style>",
    unsafe_allow_html=True,
)

st.markdown(
    clean_html(
        """
        <h1 style="text-align:center;">MANUAL CARSALES ESTIMATES</h1>
        """
    ),
    unsafe_allow_html=True,
)
st.markdown(
    "<p class='autosniper-tagline'>Enter Carsales resale and instant-buy ranges plus recent sales counts. Saved rows disappear from the list because completed items are filtered out.</p>",
    unsafe_allow_html=True,
)
st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Entry format</div>
            <div class="section-subtitle">
                Use <strong>min - max</strong> for price ranges (e.g. <code>$15,000 - $18,000</code>).
                Instant buy uses the same format. Enter the <strong>sold last 30 days</strong> count as a whole number.
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
        "manual_instant_offer_estimate",
        "manual_instant_offer_max",
        "manual_carsales_sold_30d",
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


def _load_vehicle_table() -> pd.DataFrame:
    missing = ensure_datasets_available(["vehicle_static_details.csv"])
    if missing:
        st.error("Missing dataset: vehicle_static_details.csv")
        st.stop()

    path = dataset_path("vehicle_static_details.csv")
    df = pd.read_csv(path)
    df = _ensure_columns(df)

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


df = _load_vehicle_table()

# Filters
timeframe_options: Dict[str, tuple[Optional[float], Optional[float]]] = {
    "All": (None, None),
    "Next 24h": (0.0, 24.0),
    "Next 48h": (0.0, 48.0),
    "Next 72h": (0.0, 72.0),
}
selected_timeframe = st.sidebar.selectbox("Time window", list(timeframe_options.keys()), index=1)
min_hours, max_hours = timeframe_options[selected_timeframe]

location_options = sorted({loc for loc in df["location_clean"].dropna().unique() if loc})
unique_makes = sorted({m for m in df.get("make", pd.Series()).dropna().astype(str).str.title()})
selected_makes = st.sidebar.multiselect("Filter by make", unique_makes)
selected_locations = st.sidebar.multiselect("Filter by location", location_options)

search_text = st.sidebar.text_input("Search model/variant/URL")

# Base filtering
missing_manual_mask = (
    df["manual_carsales_min"].apply(_is_blank) | df["manual_instant_offer_estimate"].apply(_is_blank)
)
status_mask = ~df["status"].isin(EXCLUDED_STATUSES)
skip_mask = ~df["carsales_skipped"].fillna(False).astype(bool)
hours_mask = pd.Series([True] * len(df))
if min_hours is not None or max_hours is not None:
    hours_mask = df["hours_remaining"].apply(
        lambda val: (
            (min_hours is None or (val is not None and val >= min_hours))
            and (max_hours is None or (val is not None and val < max_hours))
        )
    )

filtered = df[missing_manual_mask & status_mask & skip_mask & hours_mask].copy()

if selected_makes:
    filtered = filtered[filtered["make"].astype(str).str.title().isin(selected_makes)]

if selected_locations:
    filtered = filtered[filtered["location_clean"].isin(selected_locations)]

if search_text:
    needle = search_text.strip().lower()
    filtered = filtered[
        filtered["model"].astype(str).str.lower().str.contains(needle)
        | filtered["variant"].astype(str).str.lower().str.contains(needle)
        | filtered["url"].astype(str).str.lower().str.contains(needle)
    ]

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
        header_col, meta_col = st.columns([3, 2])
        header_col.markdown(f"**{html.escape(title)}**")
        header_col.caption(row.get("location_clean", "") or "Location: N/A")
        meta_col.write(row.get("odometer_display", "N/A"))
        meta_col.markdown(f"[Carsales search]({row.get('carsales_search','')})", unsafe_allow_html=False)

        resale_default = _format_range_text(row.get("manual_carsales_min"), row.get("manual_carsales_max"))
        instant_default = _format_range_text(
            row.get("manual_instant_offer_estimate"), row.get("manual_instant_offer_max")
        )
        sold_default = _safe_int(row.get("manual_carsales_sold_30d")) or 0

        resale_col, instant_col, sold_col = st.columns([2, 2, 1])
        resale_input = resale_col.text_input(
            "Carsales resale (min - max)",
            value=resale_default,
            placeholder="$15,000 - $18,000",
        )
        instant_input = instant_col.text_input(
            "Instant buy (min - max)",
            value=instant_default,
            placeholder="$12,500 - $14,000",
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
            instant_min, instant_max = _parse_range_text(instant_input)
            if manual_min is None:
                st.error("Carsales resale range is required (min or min-max).")
                continue
            if instant_min is None:
                st.error("Instant buy range is required (min or min-max).")
                continue

            updated = update_vehicle_estimates(
                url,
                manual_min=manual_min,
                manual_max=manual_max,
                manual_instant_offer=instant_min,
                manual_instant_offer_max=instant_max,
                sold_last_30d=int(sold_input) if sold_input is not None else None,
                skipped=False,
            )
            if updated:
                st.success("Saved Carsales estimates.")
                st.experimental_rerun()
            else:
                st.error("Unable to update this vehicle.")

        if skip_clicked:
            updated = update_vehicle_estimates(url, skipped=True)
            if updated:
                st.info("Skipped. You can revisit later by clearing the flag in CSV.")
                st.experimental_rerun()
            else:
                st.error("Unable to skip this vehicle.")
