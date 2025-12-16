import os

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path
from shared.styling import (
    clean_html,
    display_banner,
    inject_global_styles,
    render_logo_centered,
)


st.set_page_config(page_title="COLLECT VEHICLE LINKS", layout="wide")
inject_global_styles()
st.markdown(
    clean_html(
        """
        <style>
            div[data-testid="stVerticalBlock"]:has(> .collect-links-card-marker) {
                background: var(--autosniper-panel);
                border: 1px solid var(--autosniper-border);
                border-radius: 18px;
                box-shadow: 0 18px 32px rgba(0, 0, 0, 0.26);
                padding: 1.5rem 1.75rem 1.7rem;
                margin: 0 auto 1.25rem;
                max-width: 960px;
                text-align: center;
            }
            div[data-testid="stVerticalBlock"]:has(> .collect-links-card-marker) h1 {
                margin-bottom: 0.9rem;
            }
            div[data-testid="stVerticalBlock"]:has(> .collect-links-card-marker) .stButton {
                display: flex;
                justify-content: center;
                margin-bottom: 0.9rem;
            }
            div[data-testid="stVerticalBlock"]:has(> .collect-links-card-marker) .stButton>button {
                min-width: 220px;
            }
            div[data-testid="stVerticalBlock"]:has(> .collect-links-card-marker) p {
                margin-bottom: 0;
                color: var(--autosniper-muted);
            }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

display_banner()
render_logo_centered()

intro_box = st.container()
with intro_box:
    st.markdown('<div class="collect-links-card-marker" style="display:none;"></div>', unsafe_allow_html=True)
    st.markdown("<h1>COLLECT VEHICLE LINKS</h1>", unsafe_allow_html=True)
    run_clicked = st.button("Run link scraper", key="link_scraper_btn")
    st.markdown(
        "<p>Grab every active auction link so the rest of the toolkit can stay in sync.</p>",
        unsafe_allow_html=True,
    )

CSV_PATH = dataset_path("all_vehicle_links.csv")

if run_clicked:
    with st.spinner("Scraping vehicle links from Grays…"):
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
