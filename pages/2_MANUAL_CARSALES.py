import html
import urllib.parse
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from scripts.ai_price_analysis import _extract_hours_remaining
from scripts.vehicle_updates import coerce_price, update_vehicle_estimates
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.styling import clean_html, display_banner, inject_global_styles


st.set_page_config(page_title="Manual Carsales Estimate Input", layout="wide")
inject_global_styles()
display_banner()

st.markdown(
    clean_html(
        """
        <h1 style="text-align:center;">MANUAL CARSALES ESTIMATES</h1>
        """
    ),
    unsafe_allow_html=True,
)
st.markdown(
    "<p class='autosniper-tagline'>Open the Carsales search links, record resale and instant-offer values, or skip listings that cannot be valued right now.</p>",
    unsafe_allow_html=True,
)
st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Workflow</div>
            <div class="section-subtitle">
                Filter for auctions closing soon, jump to Carsales, then submit both pricing fields or mark a listing as skipped.
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)


EXCLUDED_STATUSES = {"sold", "closed", "canceled", "cancelled", "referred"}


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "manual_carsales_min" not in df.columns:
        df["manual_carsales_min"] = None
    if "manual_instant_offer_estimate" not in df.columns:
        df["manual_instant_offer_estimate"] = None
    if "carsales_skipped" not in df.columns:
        df["carsales_skipped"] = False
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
    df["carsales_skipped"] = df["carsales_skipped"].fillna(False)

    # Compute hours remaining for filtering when possible.
    if "hours_remaining" not in df.columns:
        df["hours_remaining"] = df.get("time_remaining_or_date_sold", "").apply(_extract_hours_remaining)

    if "auction_end_time" in df.columns:
        df["auction_end_time_parsed"] = pd.to_datetime(df["auction_end_time"], errors="coerce")
    else:
        df["auction_end_time_parsed"] = pd.NaT

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

unique_makes = sorted({m for m in df.get("make", pd.Series()).dropna().astype(str).str.title()})
selected_makes = st.sidebar.multiselect("Filter by make", unique_makes)

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

display_columns = [
    "year",
    "make",
    "model",
    "variant",
    "transmission",
    "fuel_type",
    "odometer_display",
    "manual_carsales_min",
    "manual_instant_offer_estimate",
    "carsales_search",
    "url",
]

editor_df = filtered[display_columns].rename(
    columns={
        "year": "Year",
        "make": "Make",
        "model": "Model",
        "variant": "Variant",
        "transmission": "Transmission",
        "fuel_type": "Fuel Type",
        "odometer_display": "Odometer",
        "manual_carsales_min": "manual_carsales_min",
        "manual_instant_offer_estimate": "manual_instant_offer_estimate",
        "carsales_search": "Carsales Search",
        "url": "url",
    }
)

st.markdown("Use the table to input Carsales resale and instant offer estimates, then submit each row.")

edited_df = st.data_editor(
    editor_df,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "Year": st.column_config.NumberColumn("Year", disabled=True, width="small"),
        "Make": st.column_config.TextColumn("Make", disabled=True, width="medium"),
        "Model": st.column_config.TextColumn("Model", disabled=True, width="medium"),
        "Variant": st.column_config.TextColumn("Variant", disabled=True, width="large"),
        "Transmission": st.column_config.TextColumn("Transmission", disabled=True, width="small"),
        "Fuel Type": st.column_config.TextColumn("Fuel Type", disabled=True, width="small"),
        "Odometer": st.column_config.TextColumn("Odometer", disabled=True, width="medium"),
        "manual_carsales_min": st.column_config.NumberColumn(
            "Carsales Resale (Min)",
            help="Enter the expected resale on Carsales.",
            format="$%,.0f",
        ),
        "manual_instant_offer_estimate": st.column_config.NumberColumn(
            "Instant Offer Estimate",
            help="Instant buy/offer estimate.",
            format="$%,.0f",
        ),
        "Carsales Search": st.column_config.LinkColumn("Carsales Search", display_text="Open search"),
        "url": st.column_config.TextColumn("Listing URL", disabled=True),
    },
)

st.divider()


def _validate_row(row: pd.Series) -> tuple[bool, str, Optional[float], Optional[float]]:
    manual_min = coerce_price(row.get("manual_carsales_min"))
    manual_offer = coerce_price(row.get("manual_instant_offer_estimate"))
    if manual_min is None or manual_min <= 0:
        return False, "Carsales resale estimate is required and must be positive.", None, None
    if manual_offer is None or manual_offer <= 0:
        return False, "Instant offer estimate is required and must be positive.", None, None
    return True, "", manual_min, manual_offer


for _, row in edited_df.iterrows():
    url = row["url"]
    parts = [row.get("Year"), row.get("Make"), row.get("Model"), row.get("Variant")]
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
    info_col, min_col, offer_col, submit_col, skip_col, export_col = st.columns([3, 1.2, 1.2, 0.8, 0.8, 1.2])
    info_col.markdown(f"**{html.escape(title)}**")
    min_col.write(f"Min: {row.get('manual_carsales_min') or '—'}")
    offer_col.write(f"Instant: {row.get('manual_instant_offer_estimate') or '—'}")

    submit_key = f"submit_{url}"
    skip_key = f"skip_{url}"
    export_key = f"export_{url}"

    if submit_col.button("Submit", key=submit_key):
        ok, message, manual_min_val, manual_offer_val = _validate_row(row)
        if not ok:
            st.error(message)
        else:
            updated = update_vehicle_estimates(
                url,
                manual_min=manual_min_val,
                manual_instant_offer=manual_offer_val,
                skipped=False,
            )
            if updated:
                st.success("Saved Carsales estimates.")
                st.experimental_rerun()
            else:
                st.error("Unable to update this vehicle.")

    if skip_col.button("Skip", key=skip_key):
        updated = update_vehicle_estimates(url, skipped=True)
        if updated:
            st.info("Skipped. You can revisit later by clearing the flag in CSV.")
            st.experimental_rerun()
        else:
            st.error("Unable to skip this vehicle.")

    export_payload = f"{title} | {row.get('Transmission','')} | {row.get('Fuel Type','')} | {row.get('Odometer','')} | {row.get('Carsales Search','')}"
    if export_col.button("Copy row text", key=export_key):
        st.session_state["manual_clipboard_payload"] = export_payload
        st.toast("Row text ready to copy (Ctrl+C).")
    export_col.text_input("Copy", value=export_payload, label_visibility="collapsed", key=f"copy_input_{url}")
