import asyncio
import os
import re
import textwrap

import pandas as pd
import streamlit as st

from scripts.update_bids import update_bids
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


st.set_page_config(page_title="ACTIVE LISTINGS DASHBOARD", layout="wide")
inject_global_styles()

display_banner()
page_intro("ACTIVE LISTINGS DASHBOARD", "Track live auctions, filter the noise, and act on the most promising stock.")

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
    return textwrap.shorten(text, width=width, placeholder="ΓÇª")


def combine_odometer(row: pd.Series) -> str:
    reading = safe_text(row.get("odometer_reading"), "")
    unit = safe_text(row.get("odometer_unit"), "")
    combined = f"{reading} {unit}".strip()
    return combined if combined else "N/A"


def render_listing_card(row: pd.Series) -> None:
    parts = [
        safe_text(row.get("year"), ""),
        safe_text(row.get("make"), ""),
        safe_text(row.get("model"), ""),
        safe_text(row.get("variant"), ""),
    ]
    vehicle_title = " ".join([part for part in parts if part])
    if not vehicle_title:
        vehicle_title = "Untitled listing"
    vehicle_url = row.get("url", "")
    link_html = (
        f"<a class='autosniper-link autosniper-link-button' href='{vehicle_url}' target='_blank'>Open Listing Γåù</a>"
        if vehicle_url
        else ""
    )

    stats: list[tuple[str, str]] = [
        ("Guide Price", safe_text(row.get("price"))),
        ("Current Bids", safe_text(row.get("bids"), "0")),
        ("Time Remaining", safe_text(row.get("time_remaining_or_date_sold"))),
        ("Odometer", combine_odometer(row)),
        ("Location", safe_text(row.get("location"))),
    ]

    optional_fields = [
        ("Body", row.get("body_type")),
        ("Transmission", row.get("transmission")),
        ("Engine", row.get("engine_size")),
    ]
    for label, value in optional_fields:
        if value:
            stats.append((label, safe_text(value)))

    all_stats = stats
    stats_html = "\n".join(
        clean_html(
            f"""
            <div class="autosniper-stat">
                <div class="label">{label}</div>
                <div class="value">{value}</div>
            </div>
            """
        )
        for label, value in all_stats
    )

    condition_raw = safe_text(row.get("general_condition"), "")
    condition_html = ""
    if condition_raw and condition_raw.lower() != "n/a":
        condition_html = clean_html(
            f"""
            <div class="autosniper-condition">
                <span class="label">Condition Notes</span>
                <p>{shorten_condition(condition_raw)}</p>
            </div>
            """
        )

    card_html = clean_html(
        f"""
        <div class="autosniper-listing-card">
            <div class="card-header">
                <div class="card-title">{vehicle_title}</div>
                {link_html}
            </div>
            <div class="autosniper-stats-grid">
                {stats_html}
            </div>
            {condition_html}
        </div>
        """
    )
    st.markdown(card_html, unsafe_allow_html=True)


async def run_bid_update(links: list[str] | None = None) -> None:
    with st.spinner("Updating bid and time dataΓÇª"):
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


if st.button("Refresh Active Listings"):
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


if CSV_FILE.exists():
    df = load_csv()

    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].fillna("").astype(str).str.strip()

    df["status"] = df["status"].astype(str).str.strip().str.lower()
    df = df[df["status"] == "active"]

    st.sidebar.markdown("### Filters")
    hide_engine_issues = st.sidebar.checkbox("Hide vehicles with engine defects", value=True)
    hide_unregistered = st.sidebar.checkbox("Hide unregistered vehicles", value=False)
    filter_vic_only = st.sidebar.checkbox("Show only VIC listings", value=False)

    def has_engine_issue(row: pd.Series) -> bool:
        text = str(row.get("general_condition", "")).lower()
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
        return any(kw in text for kw in keywords)

    def is_unregistered(row: pd.Series) -> bool:
        value = row.get("no_of_plates", 0)
        try:
            return int(value) == 0
        except (TypeError, ValueError):
            return False

    if hide_engine_issues:
        df = df[~df.apply(has_engine_issue, axis=1)]
    if hide_unregistered:
        df = df[~df.apply(is_unregistered, axis=1)]
    if filter_vic_only:
        df = df[df["location"].astype(str).str.upper() == "VIC"]

    if "url" in df.columns:
        visible_urls = df["url"].dropna().unique().tolist()
    else:
        visible_urls = []
    if st.button("Refresh Visible Listings"):
        if visible_urls:
            asyncio.run(run_bid_update(visible_urls))
        else:
            st.info("No listings match the current filters.")

    def time_bucket(row: pd.Series) -> str:
        time_str = str(row.get("time_remaining_or_date_sold", "")).lower()
        h_match = re.search(r"(\d+)\s*h", time_str)
        d_match = re.search(r"(\d+)\s*d", time_str)

        days = int(d_match.group(1)) if d_match else 0
        hours = int(h_match.group(1)) if h_match else 0
        total_hours = days * 24 + hours

        if total_hours < 24:
            return "< 24h"
        if total_hours < 48:
            return "1-2d"
        if total_hours < 72:
            return "2-3d"
        return "3+d"

    df["time_group"] = df.apply(time_bucket, axis=1)
    df["time_group_order"] = df["time_group"].map({"< 24h": 0, "1-2d": 1, "2-3d": 2, "3+d": 3})
    df = df.sort_values(by="time_group_order")

    grouped = df.groupby("time_group", sort=False)

    st.markdown(f"### {len(df)} Active Listings")

    if df.empty:
        st.info("No active listings match the current filters.")
    else:
        for group, group_df in grouped:
            st.markdown(f"## {group} ({len(group_df)})")
            for idx, row in group_df.iterrows():
                render_listing_card(row)
