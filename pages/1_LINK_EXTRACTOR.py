import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path
from shared.styling import (
    clean_html,
    display_banner,
    hero_action_card,
    inject_global_styles,
)


st.set_page_config(page_title="COLLECT VEHICLE LINKS", layout="wide")
inject_global_styles()

display_banner()

run_clicked = hero_action_card(
    "COLLECT VEHICLE LINKS",
    "Grab every active auction link so the rest of the toolkit can stay in sync.",
    "Run link scraper",
    button_key="link_scraper_btn",
)

CSV_PATH = dataset_path("all_vehicle_links.csv")
SUMMARY_PATH = Path("logs") / "link_scrape_summary.json"

if run_clicked:
    with st.spinner("Scraping vehicle links from Grays..."):
        exit_code = os.system("python scripts/extract_links.py")
        if exit_code == 0:
            st.success("Link scraping completed.")
        else:
            st.error("Script failed. Check the terminal output for details.")

if CSV_PATH.exists():
    df = pd.read_csv(CSV_PATH)
    total_links = len(df)
    summary = {}
    if SUMMARY_PATH.exists():
        try:
            summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        except Exception:
            summary = {}
    total_found = summary.get("total_links_found", total_links)
    skipped_existing = summary.get("skipped_existing", 0)
    filtered_new = summary.get("filtered_new_links", total_links)

    summary_html = clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Link scraper summary</div>
            <div class="section-subtitle">Latest snapshot of Grays listings.</div>
        </div>
        """
    )
    st.markdown(summary_html, unsafe_allow_html=True)
    col_total, col_new, col_skipped = st.columns(3)
    col_total.metric("Total links found", f"{total_found:,}")
    col_new.metric("New links saved", f"{filtered_new:,}")
    col_skipped.metric("Skipped (already tracked)", f"{skipped_existing:,}")

    if total_links:
        st.success(f"{total_links:,} new links ready in all_vehicle_links.csv.")
    else:
        st.info("Link file is present but contains no rows.")
else:
    st.info("Run the scraper to generate the latest list of vehicle links.")
