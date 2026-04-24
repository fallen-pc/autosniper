import subprocess
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path, ensure_datasets_available
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro


st.set_page_config(page_title="MASTER DATABASE", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "MASTER DATABASE OVERVIEW",
    "Review every vehicle snapshot - active, sold, and referred - from one command center.",
    show_logo=False,
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


def _clean_text_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.fillna("")
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    return cleaned.mask(cleaned.str.lower().isin({"nan", "none"}), "")


def _normalize_master_view(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    for column in ("make", "model", "variant", "body_type", "fuel_type", "transmission"):
        if column in working.columns:
            working[column] = _clean_text_series(working[column])
    if "make" in working.columns:
        working["make"] = working["make"].str.upper()
    return working


def render_dataset(title: str, file_path: str, columns: Iterable[str] | None = None) -> None:
    df = _normalize_master_view(load_csv(file_path))
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
        result = _run_command([sys.executable, "scripts/update_master.py"])
        if result.returncode == 0:
            st.success("Master database updated.")
            st.cache_data.clear()
        else:
            st.error("Update failed. Check the logs for more details.")
        _render_command_result(result)


@st.cache_data(ttl=0)
def load_csv(file_path: Path | str) -> pd.DataFrame:
    path = Path(file_path)
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def render_sold_inventory() -> None:
    df = _normalize_master_view(load_csv(SOLD_FILE))
    if df.empty:
        st.info("No records found for sold vehicles.")
        return

    desired_columns = [
        "year",
        "make",
        "model",
        "variant",
        "price",
        "date_sold",
        "url",
    ]
    available_columns = [col for col in desired_columns if col in df.columns]
    missing_columns = [col for col in desired_columns if col not in df.columns]
    if missing_columns:
        st.warning(
            "Sold Vehicles: Missing columns in data source "
            f"({', '.join(missing_columns)}). Showing available fields."
        )
    working_df = df[available_columns].copy()
    working_df["year_numeric"] = pd.to_numeric(working_df.get("year"), errors="coerce")

    summary_html = clean_html(
        f"""
        <div class="autosniper-section">
            <div class="section-title">Sold Vehicles</div>
            <div class="section-subtitle">Total records: {len(working_df):,}</div>
        </div>
        """
    )
    st.markdown(summary_html, unsafe_allow_html=True)

    working_df["_make_group"] = _clean_text_series(working_df.get("make", pd.Series(index=working_df.index))).str.casefold()
    working_df["_model_group"] = _clean_text_series(working_df.get("model", pd.Series(index=working_df.index))).str.casefold()
    working_df.sort_values(
        by=["_make_group", "_model_group", "year_numeric"],
        ascending=[True, True, False],
        inplace=True,
        kind="mergesort",
    )

    for make_value, make_df in working_df.groupby("_make_group", dropna=False):
        if make_value:
            make_label = str(make_value).upper()
        else:
            make_label = "UNKNOWN MAKE"
        with st.expander(f"{make_label} ({len(make_df)} vehicles)", expanded=False):
            display_df = make_df.drop(columns=["year_numeric", "_make_group", "_model_group"]).sort_values(
                by=["model", "year"],
                ascending=[True, False],
                kind="mergesort",
            )
            st.dataframe(
                display_df.reset_index(drop=True),
                width="stretch",
                hide_index=True,
            )
render_sold_inventory()

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
