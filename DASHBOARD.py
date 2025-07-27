import streamlit as st
import pandas as pd
import os

# ─── Page Config ───────────────────────────────────────────────
st.set_page_config(page_title="AutoSniper - Dashboard", layout="wide")

# ─── Header ────────────────────────────────────────────────────
st.title("🚀 AutoSniper Dashboard")
st.markdown("Welcome to your live vehicle auction sniper system. Below is an overview of all tracked listings.")

# ─── Optional Logo ─────────────────────────────────────────────
logo_path = "shared/autosniper_logo.png"
if os.path.exists(logo_path):
    st.image(logo_path, width=160)

# ─── Load Vehicle Data ─────────────────────────────────────────
CSV_FILE = "CSV_data/vehicle_static_details.csv"

if os.path.exists(CSV_FILE):
    df = pd.read_csv(CSV_FILE)

    # Normalize status column
    df["status"] = df["status"].astype(str).str.strip().str.lower()
    status_counts = df["status"].value_counts(dropna=False)

    # Summary stats
    total = len(df)
    active = status_counts.get("active", 0)
    sold = status_counts.get("sold", 0)
    referred = status_counts.get("referred", 0)
    unknown = total - active - sold - referred

    # ─── Display Summary ───────────────────────────────────────
    st.markdown("### 📊 Status Summary")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("🟢 Active", active)
    col2.metric("🔴 Sold", sold)
    col3.metric("⚪ Referred", referred)
    col4.metric("❓ Unknown", unknown)
    col5.metric("📄 Total", total)

    st.divider()

    # Optional: show sample data
    with st.expander("🔍 Preview Sample Listings", expanded=False):
        st.dataframe(df.head(10), use_container_width=True)

else:
    st.error("❌ vehicle_static_details.csv not found. Please run detail extraction first.")
