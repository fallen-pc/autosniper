import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="AI Analysis", layout="wide")
st.title("🤖 AI Pricing Analysis")

# ─── File Paths ───────────────────────────────────────────────
DETAILS_FILE = "CSV_data/vehicle_static_details.csv"
VERDICT_FILE = "CSV_data/ai_verdicts.csv"

# ─── Load Data ────────────────────────────────────────────────
if not os.path.exists(VERDICT_FILE):
    st.info("No AI analyses have been run yet.")
    st.stop()

verdict_df = pd.read_csv(VERDICT_FILE)

if not os.path.exists(DETAILS_FILE):
    st.warning("vehicle_static_details.csv not found.")
    st.stop()

details_df = pd.read_csv(DETAILS_FILE)

# ─── Match on URL ─────────────────────────────────────────────
df = pd.merge(verdict_df, details_df, on="url", suffixes=("", "_details"))

if df.empty:
    st.info("No completed AI analyses to display.")
    st.stop()

# ─── Helper for Profit Bar ────────────────────────────────────
def display_profit_bar(profit_str, verdict):
    try:
        percent = float(profit_str.strip('%'))
        bar_color = "green" if percent >= 20 else "orange" if percent >= 10 else "red"
        st.markdown(f"**Profit Margin: {profit_str} — Verdict: {verdict}**")
        st.progress(min(percent / 100, 1.0))
    except:
        st.warning("⚠️ Could not parse profit margin.")

# ─── Display Tabs for Analyzed Vehicles ───────────────────────
tabs = st.tabs([f"{row['year']} {row['make']} {row['model']} {row['variant']}" for _, row in df.iterrows()])

for tab, (_, row) in zip(tabs, df.iterrows()):
    with tab:
        st.subheader(f"{row['year']} {row['make']} {row['model']} {row['variant']}")
        st.markdown(f"[🔗 View Listing]({row['url']})", unsafe_allow_html=True)

        st.write(f"📍 Location: {row.get('location', 'N/A')}")
        st.write(f"📅 Time Remaining: {row.get('time_remaining_or_date_sold', 'N/A')}")
        st.write(f"💰 Current Bid: {row.get('price', 'N/A')} — 🔨 Bids: {row.get('bids', 'N/A')}")
        st.write(f"🧭 Odometer: {row.get('odometer_reading', 'N/A')} {row.get('odometer_unit', '')}")

        st.divider()
        st.markdown("### 💡 AI Analysis Result")
        st.write(f"🪙 **Resale Estimate:** {row['resale_estimate']}")
        st.write(f"📉 **Maximum Bid (for profit):** {row['max_bid']}")
        display_profit_bar(row['profit_margin_percent'], row['verdict'])
