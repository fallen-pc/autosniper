"""Streamlit overview dashboard for the AutoSniper dataset."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from shared.styling import clean_html, display_banner, inject_global_styles, section_heading


st.set_page_config(page_title="AutoSniper - Dashboard", layout="wide")
inject_global_styles()
display_banner()

st.markdown(
    clean_html(
        """
        <h1 style="text-align:center;">DASHBOARD</h1>
        """
    ),
    unsafe_allow_html=True,
)
st.markdown(
    clean_html(
        """
        <p style="color: var(--autosniper-muted); max-width: 720px; margin: 0 auto 1.5rem; text-align: center;">
            Monitor live stock, track state changes, and review coverage across the intake feeds.
        </p>
        """
    ),
    unsafe_allow_html=True,
)

CSV_FILE = Path("CSV_data/vehicle_static_details.csv")
if not CSV_FILE.exists():
    st.error("`CSV_data/vehicle_static_details.csv` was not found. Run the extractor to populate the dataset.")
    st.stop()

df = pd.read_csv(CSV_FILE)

if df.empty:
    st.warning("The vehicle dataset is empty. Trigger a scrape to see dashboard metrics.")
    st.stop()


def normalise_status(data: pd.DataFrame) -> pd.Series:
    """Return a clean, lower-cased status series for aggregation."""
    status_raw = data["status"] if "status" in data.columns else pd.Series(pd.NA, index=data.index)
    status_series = (
        status_raw.fillna("unknown")
        .astype(str)
        .str.strip()
        .str.lower()
        .replace({"": "unknown", "nan": "unknown"})
    )
    return status_series


status_series = normalise_status(df)
status_counts = status_series.value_counts()
total_listings = int(len(df))

tracked_statuses: list[tuple[str, str]] = [
    ("active", "Active"),
    ("sold", "Sold"),
    ("referred", "Referred"),
]
tracked_total = sum(int(status_counts.get(code, 0)) for code, _ in tracked_statuses)
other_total = max(total_listings - tracked_total, 0)


def render_metric(column: "st.delta_generator.DeltaGenerator", label: str, value: int, share: float | None = None) -> None:
    """Display a formatted metric with an optional share-of-total delta."""
    formatted_value = f"{int(value):,}"
    if share is not None and total_listings:
        column.metric(label, formatted_value, f"{share:.0%} of total")
    else:
        column.metric(label, formatted_value)


section_heading("Status Snapshot", "Distribution of tracked listings by workflow state.")
status_columns = st.columns(5)
render_metric(status_columns[0], "Total Listings", total_listings)
for idx, (code, label) in enumerate(tracked_statuses, start=1):
    count = int(status_counts.get(code, 0))
    share = (count / total_listings) if total_listings else None
    render_metric(status_columns[idx], label, count, share)
share_other = (other_total / total_listings) if total_listings else None
render_metric(status_columns[-1], "Other / Unknown", other_total, share_other)

status_table = (
    status_counts.rename_axis("Status")
    .reset_index(name="Listings")
    .assign(Share=lambda frame: frame["Listings"] / total_listings)
)
status_table["Status"] = status_table["Status"].astype(str).str.replace("_", " ").str.title()
status_table["Share"] = status_table["Share"].map(lambda value: f"{value:.1%}")

section_heading("Status Breakdown", "All statuses ranked by listing volume.")
st.dataframe(status_table, use_container_width=True, hide_index=True)


def unique_count(column: str) -> int:
    if column not in df.columns:
        return 0
    series = df[column].dropna().astype(str).str.strip()
    series = series[series != ""]
    return int(series.nunique())


section_heading("Inventory Coverage", "Distinct values across key identifiers.")
coverage_columns = st.columns(4)
coverage_config = [
    ("make", "Unique Makes"),
    ("model", "Unique Models"),
    ("auction_house", "Auction Houses"),
    ("location", "Locations"),
]
for column, (field, label) in zip(coverage_columns, coverage_config):
    column.metric(label, f"{unique_count(field):,}")


def build_top_table(column: str, display_name: str, limit: int = 10) -> pd.DataFrame | None:
    if column not in df.columns:
        return None
    series = (
        df[column]
        .fillna("Unknown")
        .astype(str)
        .str.strip()
    )
    series = series.replace("", "Unknown")
    counts = (
        series.value_counts()
        .head(limit)
        .rename_axis(display_name)
        .reset_index(name="Listings")
    )
    return counts


section_heading("Top Sources & Makes", "Highest-volume channels in the current dataset.")
top_columns = st.columns(2)
with top_columns[0]:
    st.markdown("**By Auction House**")
    auction_house_table = build_top_table("auction_house", "Auction House")
    if auction_house_table is not None and not auction_house_table.empty:
        st.dataframe(auction_house_table, use_container_width=True, hide_index=True)
    else:
        st.info("No auction house data captured yet.")

with top_columns[1]:
    st.markdown("**By Make**")
    make_table = build_top_table("make", "Make")
    if make_table is not None and not make_table.empty:
        st.dataframe(make_table, use_container_width=True, hide_index=True)
    else:
        st.info("No make data available.")


section_heading("Sample Listings", "Preview the first 10 records from the master file.")
st.dataframe(df.head(10), use_container_width=True, hide_index=True)
