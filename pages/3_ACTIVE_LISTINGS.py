import asyncio
import os
import re
import textwrap

import pandas as pd
import streamlit as st

from scripts.update_bids import update_bids
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.filter_controls import (
    apply_vehicle_filters,
    render_time_filter,
    render_vehicle_filter_toggles,
)
from shared.styling import (
    clean_html,
    display_banner,
    hero_action_card,
    inject_global_styles,
    render_logo_centered,
)

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


st.set_page_config(page_title="ACTIVE LISTINGS DASHBOARD", layout="wide")
inject_global_styles()

display_banner()
render_logo_centered()

missing = ensure_datasets_available(["vehicle_static_details.csv"])
if missing:
    st.error(
        "Required dataset `vehicle_static_details.csv` is missing. "
        "Configure `AUTOSNIPER_DATA_URL` or upload the CSV to `CSV_data/`."
    )
    st.stop()

CSV_FILE = dataset_path("vehicle_static_details.csv")

if "skipped_urls" not in st.session_state:
    st.session_state.skipped_urls = []


def safe_text(value: object, default: str = "N/A") -> str:
    """Return a clean string for display, substituting a default when empty."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    return text if text else default


def shorten_condition(text: str, width: int = 160) -> str:
    if not text:
        return ""
    return textwrap.shorten(text, width=width, placeholder="...")


def combine_odometer(row: pd.Series) -> str:
    reading = safe_text(row.get("odometer_reading"), "")
    unit = safe_text(row.get("odometer_unit"), "")
    combined = f"{reading} {unit}".strip()
    return combined if combined else "N/A"


def parse_time_remaining_hours(value: object) -> float | None:
    """Convert 'Xd Yh Zm' strings into total hours for filtering."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    if not text or any(keyword in text for keyword in ("sold", "ended", "closed")):
        return None

    day_matches = re.findall(r"(\d+)\s*d", text)
    hour_matches = re.findall(r"(\d+)\s*h", text)
    minute_matches = re.findall(r"(\d+)\s*m", text)

    total_hours = sum(int(val) for val in day_matches) * 24
    total_hours += sum(int(val) for val in hour_matches)
    total_hours += sum(int(val) for val in minute_matches) / 60

    if total_hours == 0:
        clock_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if clock_match:
            total_hours = int(clock_match.group(1)) + int(clock_match.group(2)) / 60

    return total_hours if total_hours > 0 else None


async def run_bid_update(links: list[str] | None = None) -> None:
    with st.spinner("Updating bid and time data..."):
        df, skipped_urls = await update_bids(input_links=links)
        st.session_state.skipped_urls = skipped_urls
        if not df.empty:
            st.success(f"Updated {len(df)} listings in {CSV_FILE}.")
        else:
            st.error("Update failed. Check logs or terminal output.")
        if skipped_urls:
            st.warning(f"Skipped {len(skipped_urls)} URLs. See the table below.")
        else:
            st.info("No URLs were skipped.")
        st.cache_data.clear()


refresh_all_clicked = hero_action_card(
    "ACTIVE LISTINGS DASHBOARD",
    "Track live auctions in a sortable grid, then refresh bid data before you strike.",
    "Refresh every listing",
    button_key="refresh_all_listings",
)

if refresh_all_clicked:
    asyncio.run(run_bid_update())

if st.session_state.skipped_urls:
    skipped_html = clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Skipped URLs</div>
            <div class="section-subtitle">
                These links could not be processed in the last run. Re-run the scraper below to retry them.
            </div>
        </div>
        """
    )
    st.markdown(skipped_html, unsafe_allow_html=True)
    skipped_df = pd.DataFrame(st.session_state.skipped_urls, columns=["URL"])
    st.dataframe(skipped_df, width="stretch")
    if st.button("Re-run scraper with skipped URLs"):
        asyncio.run(run_bid_update(st.session_state.skipped_urls))


@st.cache_data(ttl=0)
def load_csv() -> pd.DataFrame:
    return pd.read_csv(CSV_FILE)


def assemble_vehicle_title(row: pd.Series) -> str:
    parts = [
        safe_text(row.get("year"), ""),
        safe_text(row.get("make"), ""),
        safe_text(row.get("model"), ""),
        safe_text(row.get("variant"), ""),
    ]
    title = " ".join(part for part in parts if part)
    return title or "Untitled listing"


if CSV_FILE.exists():
    df = load_csv()

    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].fillna("").astype(str).str.strip()

    df["status"] = df["status"].astype(str).str.strip().str.lower()
    active_df = df[df["status"] == "active"].copy()

    if active_df.empty:
        st.info("No active listings available. Refresh the scrapers to pull the latest data.")
        st.stop()

    st.sidebar.markdown("### Filters")
    time_choice, time_bounds = render_time_filter(
        container=st.sidebar,
        label="Time remaining",
        default_option="< 24h",
    )
    vehicle_toggles = render_vehicle_filter_toggles(container=st.sidebar)

    filtered_df = apply_vehicle_filters(active_df, vehicle_toggles)
    filtered_df = filtered_df.copy()
    filtered_df["time_remaining_hours"] = filtered_df["time_remaining_or_date_sold"].apply(parse_time_remaining_hours)
    filtered_df["vehicle_name"] = filtered_df.apply(assemble_vehicle_title, axis=1)
    filtered_df["odometer_display"] = filtered_df.apply(combine_odometer, axis=1)
    filtered_df["condition_short"] = filtered_df["general_condition"].apply(
        lambda text: shorten_condition(safe_text(text, ""), width=140)
    )

    lower_bound, upper_bound = time_bounds
    if lower_bound is not None or upper_bound is not None:
        scoped_df = filtered_df[filtered_df["time_remaining_hours"].notna()]
        if lower_bound is not None:
            scoped_df = scoped_df[scoped_df["time_remaining_hours"] >= lower_bound]
        if upper_bound is not None:
            scoped_df = scoped_df[scoped_df["time_remaining_hours"] < upper_bound]
    else:
        scoped_df = filtered_df

    scoped_df = scoped_df.sort_values(by=["time_remaining_hours", "time_remaining_or_date_sold"], na_position="last")

    if "url" in scoped_df.columns:
        visible_urls = scoped_df["url"].dropna().unique().tolist()
    else:
        visible_urls = []

    col_left, col_right = st.columns([3, 1])
    with col_right:
        if st.button("Refresh visible listings"):
            if visible_urls:
                asyncio.run(run_bid_update(visible_urls))
            else:
                st.info("No listings match the current filters.")

    summary_html = clean_html(
        f"""
        <div class="autosniper-section">
            <div class="section-title">Active Vehicle Listings</div>
            <div class="section-subtitle">
                Showing {len(scoped_df):,} of {len(filtered_df):,} filtered records · {time_choice}
            </div>
        </div>
        """
    )
    col_left.markdown(summary_html, unsafe_allow_html=True)

    if scoped_df.empty:
        st.info("No active listings match the current filters.")
    else:
        table_df = scoped_df[
            [
                "vehicle_name",
                "time_remaining_or_date_sold",
                "price",
                "bids",
                "odometer_display",
                "location",
                "condition_short",
                "url",
            ]
        ].rename(
            columns={
                "vehicle_name": "Vehicle",
                "time_remaining_or_date_sold": "Time Remaining",
                "price": "Guide Price",
                "bids": "Bids",
                "odometer_display": "Odometer",
                "location": "Location",
                "condition_short": "Condition Notes",
                "url": "Listing",
            }
        )

        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Guide Price": st.column_config.Column("Guide Price ($)"),
                "Listing": st.column_config.LinkColumn("Listing", display_text="Open"),
            },
        )
