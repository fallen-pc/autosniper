import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="Master Database", layout="wide")
st.title("📊 Master Database")

# File paths
DETAILS_FILE = "CSV_data/vehicle_static_details.csv"
SOLD_FILE = "CSV_data/sold_cars.csv"
REFERRED_FILE = "CSV_data/referred_cars.csv"

# Run update script
if st.button("🚀 Update Master Database"):
    with st.spinner("Updating master database..."):
        exit_code = os.system("python scripts/update_master.py")
        if exit_code == 0:
            st.success("✅ Master database updated.")
            st.cache_data.clear()
        else:
            st.error("❌ Update failed. Check logs.")

# Load and display data
@st.cache_data(ttl=0)
def load_csv(file_path):
    return pd.read_csv(file_path) if os.path.exists(file_path) else pd.DataFrame()

# Function to create clickable URL for display only
def make_clickable(url):
    return f'<a href="{url}" target="_blank">Link</a>' if pd.notna(url) and url.startswith("http") else "N/A"

# Display Active Listings
st.markdown("### 🟢 Active Listings")
active_df = load_csv(DETAILS_FILE)
if not active_df.empty:
    st.write(f"Total active listings: {len(active_df)}")
    # Create a display DataFrame with clickable URLs
    display_df = active_df[["year", "make", "model", "variant", "price", "bids", "time_remaining_or_date_sold", "url"]].copy()
    display_df["url"] = display_df["url"].apply(make_clickable)
    st.dataframe(display_df, use_container_width=True)
else:
    st.info("No active listings found.")

# Display Sold Listings
st.markdown("### 🔴 Sold Listings")
sold_df = load_csv(SOLD_FILE)
if not sold_df.empty:
    st.write(f"Total sold listings: {len(sold_df)}")
    display_df = sold_df[["year", "make", "model", "variant", "price", "bids", "time_remaining_or_date_sold", "url"]].copy()
    display_df["url"] = display_df["url"].apply(make_clickable)
    st.dataframe(display_df, use_container_width=True)
else:
    st.info("No sold listings found.")

# Display Referred/Canceled/Closed Listings
st.markdown("### ⚪ Referred/Canceled/Closed Listings")
referred_df = load_csv(REFERRED_FILE)
if not referred_df.empty:
    st.write(f"Total referred/canceled/closed listings: {len(referred_df)}")
    display_df = referred_df[["year", "make", "model", "variant", "price", "bids", "time_remaining_or_date_sold", "url"]].copy()
    display_df["url"] = display_df["url"].apply(make_clickable)
    st.dataframe(display_df, use_container_width=True)
else:
    st.info("No referred/canceled/closed listings found.")
