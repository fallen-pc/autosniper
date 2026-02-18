from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path
from shared.ops_utils import load_active_df, load_static_df, load_valuations_df
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Health - Pipeline", layout="wide")
inject_global_styles()
display_banner()
page_intro("PIPELINE HEALTH", "Counts, freshness, and error signals.", show_logo=False)


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _last_run(path: Path) -> str:
    if not path.exists():
        return "never"
    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    local_ts = ts.astimezone().strftime("%Y-%m-%d %H:%M")
    return f"{local_ts}"


links_path = dataset_path("all_vehicle_links.csv")
static_path = dataset_path("vehicle_static_details.csv")
active_path = dataset_path("active_vehicle_details.csv")
valuations_path = dataset_path("ai_listing_valuations.csv")
sold_path = dataset_path("sold_cars.csv")
referred_path = dataset_path("referred_cars.csv")
failures_path = dataset_path("excluded_listings.csv")
legacy_failures_path = dataset_path("scrape_failures.csv")

links_df = _load_csv(links_path)
static_df = load_static_df()
active_df = load_active_df()
valuations_df = load_valuations_df()
sold_df = _load_csv(sold_path)
referred_df = _load_csv(referred_path)

section_heading("Pipeline Counts", "Are the numbers flowing correctly?")
metrics = st.columns(6)
metrics[0].metric("Links", f"{len(links_df):,}")
metrics[1].metric("Static", f"{len(static_df):,}")
metrics[2].metric("Active", f"{len(active_df):,}")
metrics[3].metric("Valuations", f"{len(valuations_df):,}")
metrics[4].metric("Sold", f"{len(sold_df):,}")
metrics[5].metric("Referred", f"{len(referred_df):,}")

section_heading("Freshness", "Last write time for each feed.")

freshness = {
    "links_last_run": _last_run(links_path),
    "static_last_run": _last_run(static_path),
    "active_last_run": _last_run(active_path),
    "valuations_last_run": _last_run(valuations_path),
    "sold_last_run": _last_run(sold_path),
    "referred_last_run": _last_run(referred_path),
}

st.write(freshness)

section_heading("Status Mix", "Active vs non-active ratios.")
if active_df.empty or "status" not in active_df.columns:
    st.info("No status data available yet.")
else:
    status_counts = active_df["status"].astype(str).str.lower().value_counts(dropna=False)
    total = int(status_counts.sum()) if not status_counts.empty else 0
    not_active = int(status_counts.drop(labels=["active"], errors="ignore").sum())
    withdrawn_rate = (not_active / total) if total else 0
    st.write({
        "status_counts": status_counts.to_dict(),
        "not_active_rate": f"{withdrawn_rate:.1%}",
    })

section_heading("Error Logs", "Top failure reasons from excluded_listings.csv.")
log_path = failures_path if failures_path.exists() else legacy_failures_path
if log_path.exists():
    if log_path == legacy_failures_path and not failures_path.exists():
        st.caption("Using legacy scrape_failures.csv (excluded_listings.csv not found yet).")
    failures_df = pd.read_csv(log_path, usecols=["timestamp", "reason_code"], nrows=50000)
    if failures_df.empty:
        st.info("No scrape failures recorded.")
    else:
        failures_df["timestamp"] = pd.to_datetime(failures_df["timestamp"], errors="coerce")
        reason_counts = failures_df["reason_code"].fillna("Unknown").value_counts().head(20)
        st.dataframe(reason_counts.reset_index(name="count"), use_container_width=True, hide_index=True)
else:
    st.info("excluded_listings.csv not found.")
