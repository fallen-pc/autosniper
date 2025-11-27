import os
from pathlib import Path
from typing import Iterable

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path, ensure_datasets_available
from shared.styling import clean_html, display_banner, inject_global_styles


st.set_page_config(page_title="MASTER DATABASE", layout="wide")
inject_global_styles()
display_banner()
st.markdown(
    clean_html(
        """
        <h1 style="text-align:center;">MASTER DATABASE OVERVIEW</h1>
        """
    ),
    unsafe_allow_html=True,
)
st.markdown(
    "<p class='autosniper-tagline'>Review every vehicle snapshot - active, sold, and referred - from one command center.</p>",
    unsafe_allow_html=True,
)

required_files = [
    "vehicle_static_details.csv",
    "sold_cars.csv",
    "referred_cars.csv",
]
missing = ensure_datasets_available(required_files)
if missing:
    st.error(
        "Missing required datasets: "
        + ", ".join(missing)
        + ". Configure `AUTOSNIPER_DATA_URL` or upload the files to `CSV_data/`."
    )
    st.stop()

DETAILS_FILE = dataset_path("vehicle_static_details.csv")
SOLD_FILE = dataset_path("sold_cars.csv")
REFERRED_FILE = dataset_path("referred_cars.csv")


def render_dataset(title: str, file_path: str, columns: Iterable[str] | None = None) -> None:
    df = load_csv(file_path)
    if df.empty:
        st.info(f"No records found for {title.lower()}.")
        return

    displayed_df = df
    if columns:
        selected_columns = [col for col in columns if col in df.columns]
        missing_columns = [col for col in columns if col not in df.columns]
        if missing_columns:
            st.warning(
                f"{title}: Missing columns in data source ({', '.join(missing_columns)}). Showing available fields."
            )
        if selected_columns:
            displayed_df = df[selected_columns]

    summary_html = clean_html(
        f"""
        <div class="autosniper-section">
            <div class="section-title">{title}</div>
            <div class="section-subtitle">Total records: {len(displayed_df):,}</div>
        </div>
        """
    )
    st.markdown(summary_html, unsafe_allow_html=True)
    st.dataframe(displayed_df.head(200), width="stretch")


if st.button("Update Master Database"):
    with st.spinner("Updating master database…"):
        exit_code = os.system("python scripts/update_master.py")
        if exit_code == 0:
            st.success("Master database updated.")
            st.cache_data.clear()
        else:
            st.error("Update failed. Check the logs for more details.")


@st.cache_data(ttl=0)
def load_csv(file_path: Path | str) -> pd.DataFrame:
    path = Path(file_path)
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


render_dataset(
    "Active Listings",
    DETAILS_FILE,
    columns=[
        "year",
        "make",
        "model",
        "variant",
        "price",
        "bids",
        "time_remaining_or_date_sold",
        "status",
        "url",
    ],
)

render_dataset(
    "Sold Vehicles",
    SOLD_FILE,
    columns=[
        "year",
        "make",
        "model",
        "variant",
        "price",
        "sale_price",
        "date_sold",
        "url",
    ],
)

render_dataset(
    "Referred Vehicles",
    REFERRED_FILE,
    columns=[
        "year",
        "make",
        "model",
        "variant",
        "price",
        "referral_reason",
        "url",
    ],
)
