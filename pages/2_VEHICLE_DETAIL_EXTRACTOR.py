import os

import pandas as pd
import streamlit as st

from shared.styling import clean_html, display_banner, inject_global_styles


st.set_page_config(page_title="EXTRACT VEHICLE DETAILS", layout="wide")
inject_global_styles()

display_banner()
st.markdown(
    clean_html(
        """
        <h1 style="text-align:center;">EXTRACT VEHICLE DETAILS</h1>
        """
    ),
    unsafe_allow_html=True,
)
st.markdown(
    "<p class='autosniper-tagline'>Compile the latest specs, condition notes, and pricing signals for every tracked vehicle.</p>",
    unsafe_allow_html=True,
)

LINKS_FILE = "CSV_data/all_vehicle_links.csv"
OUTPUT_FILE = "CSV_data/vehicle_static_details.csv"

if st.button("Run detail scraper"):
    if not os.path.exists(LINKS_FILE):
        st.error("The links CSV is missing. Collect links before running the detail scraper.")
    else:
        with st.spinner("Extracting vehicle details from Grays listings…"):
            exit_code = os.system("python scripts/extract_vehicle_details.py")
            if exit_code == 0:
                st.success("Vehicle details successfully extracted.")
            else:
                st.error("Script failed. Check the terminal or logs for more information.")

if os.path.exists(OUTPUT_FILE):
    try:
        df = pd.read_csv(OUTPUT_FILE)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read {OUTPUT_FILE}: {exc}")
    else:
        if df.empty or df.columns.size == 0:
            st.warning("No vehicle details found in the CSV.")
        else:
            summary_html = clean_html(
                f"""
                <div class="autosniper-section">
                    <div class="section-title">Extracted Vehicle Listings</div>
                    <div class="section-subtitle">Total listings captured: {len(df):,}</div>
                </div>
                """
            )
            st.markdown(summary_html, unsafe_allow_html=True)
            st.dataframe(df.head(50), use_container_width=True)
else:
    st.info("Run the detail scraper to populate the vehicle dataset.")
