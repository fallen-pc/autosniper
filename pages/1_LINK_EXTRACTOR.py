import os

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path
from shared.styling import (
    clean_html,
    display_banner,
    hero_action_card,
    inject_global_styles,
    render_logo_centered,
)


st.set_page_config(page_title="COLLECT VEHICLE LINKS", layout="wide")
inject_global_styles()

display_banner()
render_logo_centered()

run_clicked = hero_action_card(
    "COLLECT VEHICLE LINKS",
    "Grab every active auction link so the rest of the toolkit can stay in sync.",
    "Run link scraper",
    button_key="link_scraper_btn",
)

CSV_PATH = dataset_path("all_vehicle_links.csv")

if run_clicked:
    with st.spinner("Scraping vehicle links from Grays..."):
        exit_code = os.system("python scripts/extract_links.py")
        if exit_code == 0:
            st.success("Link scraping completed.")
        else:
            st.error("Script failed. Check the terminal output for details.")

if CSV_PATH.exists():
    df = pd.read_csv(CSV_PATH)
    display_df = df.head(20).copy()
    if not display_df.empty:
        summary_html = clean_html(
            f"""
            <div class="autosniper-section">
                <div class="section-title">Latest Extracted Links</div>
                <div class="section-subtitle">Total links collected: {len(df):,}</div>
            </div>
            """
        )
        st.markdown(summary_html, unsafe_allow_html=True)
        st.dataframe(display_df, width="stretch")
    else:
        st.info("Link file is present but contains no rows.")
else:
    st.info("Run the scraper to generate the latest list of vehicle links.")
