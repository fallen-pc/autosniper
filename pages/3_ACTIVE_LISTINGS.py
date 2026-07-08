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
)

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


st.set_page_config(page_title="ACTIVE LISTINGS DASHBOARD", layout="wide")
inject_global_styles()

display_banner()

missing = ensure_datasets_available(["active_vehicle_details.csv"])
if missing:
    st.error(
        "Required dataset `active_vehicle_details.csv` is missing. "
        "Configure `AUTOSNIPER_DATA_URL` or upload the CSV to `CSV_data/`."
    )
    st.stop()

CSV_FILE = dataset_path("active_vehicle_details.csv")
STATUS_OPTIONS: dict[str, str] = {
    "active": "Active",
    "sold": "Sold",
    "referred": "Referred",
}

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


@st.cache_data(ttl=0)
def load_csv() -> pd.DataFrame:
    return pd.read_csv(CSV_FILE)


def _is_blank_series(series: pd.Series) -> pd.Series:
    lowered = series.astype(str).str.strip().str.lower()
    return lowered.isin(["", "nan", "none"])


def _missing_bid_urls(df: pd.DataFrame) -> list[str]:
    if df.empty or "url" not in df.columns:
        return []
    if "status" in df.columns:
        status_series = df["status"].astype(str).str.strip().str.lower()
    else:
        status_series = pd.Series("active", index=df.index)
    if "time_remaining_or_date_sold" not in df.columns:
        df = df.copy()
        df["time_remaining_or_date_sold"] = ""
    blank_price = _is_blank_series(df["price"]) if "price" in df.columns else pd.Series(False, index=df.index)
    blank_bids = _is_blank_series(df["bids"]) if "bids" in df.columns else pd.Series(False, index=df.index)
    blank_time = _is_blank_series(df["time_remaining_or_date_sold"])
    missing_mask = (status_series == "active") & (blank_price | blank_bids | blank_time)
    return df.loc[missing_mask, "url"].dropna().unique().tolist()


async def run_bid_update(links: list[str] | None = None, limit: int | None = None) -> None:
    target_links = links
    limit_arg = limit
    if target_links and limit_arg:
        target_links = target_links[:limit_arg]
        limit_arg = None
    with st.spinner("Updating bid and time data..."):
        df, skipped_urls = await update_bids(input_links=target_links, limit=limit_arg)
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
active_batch_size = st.number_input(
    "Active scraper batch size",
    min_value=0,
    max_value=500,
    value=0,
    step=1,
    help="Process only this many listings per run (0 = refresh every available listing).",
    key="active_batch_size_input",
)

if refresh_all_clicked:
    asyncio.run(run_bid_update(limit=int(active_batch_size) if active_batch_size > 0 else None))

if st.button("Refresh listings missing bid/price/time", key="refresh_missing_listings_top"):
    df = load_csv() if CSV_FILE.exists() else pd.DataFrame()
    missing_urls = _missing_bid_urls(df)
    if missing_urls:
        asyncio.run(
            run_bid_update(
                missing_urls,
                limit=int(active_batch_size) if active_batch_size > 0 else None,
            )
        )
    else:
        st.info("No listings are missing bid/price/time data.")

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
        asyncio.run(
            run_bid_update(
                st.session_state.skipped_urls,
                limit=int(active_batch_size) if active_batch_size > 0 else None,
            )
        )


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

    if "status" not in df.columns:
        df["status"] = "active"
    df["status"] = df["status"].astype(str).str.strip().str.lower()
    if "time_remaining_or_date_sold" not in df.columns:
        df["time_remaining_or_date_sold"] = ""

    missing_urls = _missing_bid_urls(df)
    if missing_urls:
        st.warning(f"{len(missing_urls):,} listings are missing bid/price/time data.")
        if st.button("Refresh newly added listings", key="refresh_missing_rows"):
            asyncio.run(
                run_bid_update(
                    missing_urls,
                    limit=int(active_batch_size) if active_batch_size > 0 else None,
                )
            )

    available_statuses = [status for status in STATUS_OPTIONS if status in df["status"].unique()]
    if not available_statuses:
        st.info("No listings available. Refresh the scrapers to pull the latest data.")
        st.stop()

    st.sidebar.markdown("### Filters")
    status_selection = st.sidebar.multiselect(
        "Listing status",
        options=available_statuses,
        default=available_statuses,
        format_func=lambda value: STATUS_OPTIONS.get(value, value.title()),
    )
    status_filtered_df = df[df["status"].isin(status_selection)].copy() if status_selection else df.copy()
    if status_filtered_df.empty:
        st.info("No listings match the selected statuses. Adjust the filters or refresh the scrapers.")
        st.stop()
    time_choice, time_bounds = render_time_filter(
        container=st.sidebar,
        label="Time remaining",
        default_option="All",
    )
    vehicle_toggles = render_vehicle_filter_toggles(container=st.sidebar)

    filtered_df = apply_vehicle_filters(status_filtered_df, vehicle_toggles)
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

    for required_col in ("price", "bids"):
        if required_col not in scoped_df.columns:
            scoped_df[required_col] = ""

    col_left, col_right = st.columns([3, 1])
    with col_right:
        if st.button("Refresh visible listings"):
            if visible_urls:
                asyncio.run(
                    run_bid_update(
                        visible_urls,
                        limit=int(active_batch_size) if active_batch_size > 0 else None,
                    )
                )
            else:
                st.info("No listings match the current filters.")

    summary_html = clean_html(
        f"""
        <div class="autosniper-section">
            <div class="section-title">Vehicle Listings</div>
            <div class="section-subtitle">
                Showing {len(scoped_df):,} of {len(filtered_df):,} filtered records · {time_choice}
            </div>
        </div>
        """
    )
    col_left.markdown(summary_html, unsafe_allow_html=True)

    if scoped_df.empty:
        st.info("No listings match the current filters.")
    else:
        table_df = scoped_df[
            [
                "vehicle_name",
                "status",
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
                "status": "Status",
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
            width="stretch",
            hide_index=True,
            column_config={
                "Guide Price": st.column_config.Column("Guide Price ($)"),
                "Listing": st.column_config.LinkColumn("Listing", display_text="Open"),
            },
        )
