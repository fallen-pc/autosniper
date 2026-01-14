import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path
from shared.styling import inject_global_styles, page_intro


st.set_page_config(page_title="Bidder Insights", layout="wide")
inject_global_styles()
page_intro(
    "BIDDER INSIGHTS",
    "Analyze bid history for repeat bidders, multi-vehicle activity, and reserve met patterns.",
)


def _load_csv(path: str) -> pd.DataFrame:
    file_path = dataset_path(path)
    if not file_path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(file_path)
    except Exception:
        return pd.DataFrame()


bidders_df = _load_csv("bid_history_bidders.csv")
listings_df = _load_csv("bid_history_listings.csv")

st.sidebar.header("Filters")
min_listings = st.sidebar.number_input("Min listings per bidder", min_value=1, value=2, step=1)
min_bids = st.sidebar.number_input("Min bids per bidder", min_value=1, value=3, step=1)

filtered_bidders = bidders_df.copy()
if not filtered_bidders.empty:
    filtered_bidders = filtered_bidders[
        (filtered_bidders["listings"] >= min_listings)
        & (filtered_bidders["bid_count"] >= min_bids)
    ]

st.subheader("Repeat Bidders")
if filtered_bidders.empty:
    st.info("No bidder summaries available. Run `scripts/analyze_bid_history.py` after scraping.")
else:
    display_cols = ["bidder_name", "listings", "bid_count", "avg_bid", "max_bid", "reserve_met_count"]
    display = filtered_bidders[display_cols].copy()
    for col in ("avg_bid", "max_bid"):
        display[col] = display[col].apply(lambda val: f"${val:,.0f}" if pd.notna(val) else "N/A")
    st.dataframe(display, use_container_width=True)

st.divider()

st.subheader("Listings With Most Bidders")
if listings_df.empty:
    st.info("No listing summaries available. Run `scripts/analyze_bid_history.py` after scraping.")
else:
    listing_cols = ["url", "bidders", "bid_rows", "max_bid", "reserve_met"]
    display = listings_df[listing_cols].copy()
    display["max_bid"] = display["max_bid"].apply(lambda val: f"${val:,.0f}" if pd.notna(val) else "N/A")
    st.dataframe(display, use_container_width=True)
