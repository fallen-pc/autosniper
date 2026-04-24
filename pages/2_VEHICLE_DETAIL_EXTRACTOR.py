import subprocess
import sys
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


st.set_page_config(page_title="EXTRACT VEHICLE DETAILS", layout="wide")
inject_global_styles()

display_banner()
run_details_clicked = hero_action_card(
    "EXTRACT VEHICLE DETAILS",
    "Compile the latest specs, condition notes, and pricing signals for every tracked vehicle.",
    "Run detail scraper",
    button_key="detail_scraper_btn",
)

LINKS_FILE = dataset_path("all_vehicle_links.csv")
OUTPUT_FILE = dataset_path("vehicle_static_details.csv")
ROOT_DIR = Path(__file__).resolve().parent.parent


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def _render_command_result(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout.strip():
        st.code(result.stdout, language="text")
    if result.stderr.strip():
        st.code(result.stderr, language="text")


detail_batch_size = st.number_input(
    "Detail scraper batch size",
    min_value=0,
    max_value=500,
    value=0,
    step=1,
    help="Process only this many listings per run (0 = scrape the entire queue).",
    key="detail_batch_size_input",
)

if run_details_clicked:
    if not LINKS_FILE.exists():
        st.error("The links CSV is missing. Collect links before running the detail scraper.")
    else:
        with st.spinner("Extracting vehicle details from Grays listings..."):
            command = [sys.executable, "scripts/extract_vehicle_details.py"]
            if detail_batch_size > 0:
                command.extend(["--batch-size", str(int(detail_batch_size))])
            result = _run_command(command)
            if result.returncode == 0:
                st.success("Vehicle details successfully extracted.")
            else:
                st.error("Script failed. Check the terminal or logs for more information.")
            _render_command_result(result)

if OUTPUT_FILE.exists():
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
        st.dataframe(df.head(50), width="stretch")
else:
    st.info("Run the detail scraper to populate the vehicle dataset.")
