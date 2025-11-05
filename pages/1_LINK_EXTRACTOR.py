import os

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path
from shared.styling import clean_html, display_banner, inject_global_styles


st.set_page_config(page_title="COLLECT VEHICLE LINKS", layout="wide")
inject_global_styles()

display_banner()
st.markdown(
    clean_html(
        """
        <h1 style="text-align:center;">COLLECT VEHICLE LINKS</h1>
        """
    ),
    unsafe_allow_html=True,
)
st.markdown(
    "<p class='autosniper-tagline'>Grab every active auction link so the rest of the toolkit can stay in sync.</p>",
    unsafe_allow_html=True,
)

CSV_PATH = dataset_path("all_vehicle_links.csv")

if st.button("Run link scraper"):
    with st.spinner("Scraping vehicle links from Grays…"):
        exit_code = os.system("python scripts/extract_links.py")
        if exit_code == 0:
            st.success("Link scraping completed.")
        else:
            st.error("Script failed. Check the terminal output for details.")

if CSV_PATH.exists():
    df = pd.read_csv(CSV_PATH)
    summary_html = clean_html(
        f"""
        <div class="autosniper-section">
            <div class="section-title">Latest Extracted Links</div>
            <div class="section-subtitle">Total links collected: {len(df):,}</div>
        </div>
        """
    )
    st.markdown(summary_html, unsafe_allow_html=True)
    st.dataframe(df.head(20), use_container_width=True)
else:
    st.info("Run the scraper to generate the latest list of vehicle links.")
