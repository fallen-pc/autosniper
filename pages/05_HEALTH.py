from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from shared.navigation import render_sidebar_navigation

from shared.csv_utils import read_csv_or_empty
from shared.data_loader import dataset_path
from shared.ops_utils import load_active_df, load_static_df, load_valuations_df
from shared.scraper_health import friendly_health_failure, load_scraper_health_report
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Health - Pipeline", layout="wide")
render_sidebar_navigation()
inject_global_styles()
display_banner()
page_intro("PIPELINE HEALTH", "Counts, freshness, and error signals.", show_logo=False)


def _load_csv(path: Path) -> pd.DataFrame:
    return read_csv_or_empty(path)


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
curve_coverage_report_path = Path("output/governance/curve_coverage.csv")
curve_monotonicity_report_path = Path("output/governance/curve_monotonicity.csv")

with st.spinner("Loading current pipeline health…"):
    links_df = _load_csv(links_path)
    static_df = load_static_df()
    active_df = load_active_df()
    valuations_df = load_valuations_df()
    sold_df = _load_csv(sold_path)
    referred_df = _load_csv(referred_path)
    health_report = load_scraper_health_report()

section_heading("Automated Snapshot", "Latest scheduler-written health signals.")
if not health_report:
    st.info("No automated health snapshot is available yet. Dataset counts and freshness are shown below.")
else:
    generated_at = str(health_report.get("generated_at") or "")
    job_name = str(health_report.get("job_name") or "")
    job_status = str(health_report.get("job_status") or "")
    error_message = str(health_report.get("error_message") or "")
    if generated_at:
        st.caption(f"Generated: {generated_at}")
    status_cols = st.columns(2)
    status_cols[0].metric("Latest job", job_name or "Unknown")
    status_cols[1].metric("Status", (job_status or "Unknown").replace("_", " ").title())
    if error_message:
        st.warning(friendly_health_failure(job_name, error_message))

    stage_metrics = health_report.get("stage_metrics") or {}
    if stage_metrics:
        stage_df = pd.DataFrame(stage_metrics.values())
        if not stage_df.empty:
            excluded_stage = stage_df.get("source", pd.Series(dtype=str)).astype(str).eq("excluded")
            stage_df.loc[excluded_stage, "label"] = "Exclusion log freshness"
            stage_df.loc[
                excluded_stage & stage_df["status"].astype(str).ne("healthy"),
                "status",
            ] = "stale"
            st.dataframe(stage_df, use_container_width=True, hide_index=True)

    stale_datasets = health_report.get("stale_datasets") or []
    if stale_datasets:
        stale_labels = {
            "excluded": "exclusion log",
        }
        readable_stale = [stale_labels.get(str(value), str(value)) for value in stale_datasets]
        st.warning("Stale or degraded datasets: " + ", ".join(sorted(set(readable_stale))))

    failure_reasons = pd.DataFrame(health_report.get("top_failure_reasons") or [])
    if not failure_reasons.empty:
        section_heading("Top Failure Reasons", "Latest aggregated pipeline failure reasons.")
        st.dataframe(failure_reasons, use_container_width=True, hide_index=True)

if curve_coverage_report_path.exists() or curve_monotonicity_report_path.exists():
    section_heading("Governance Reports", "Automated curve coverage and monotonicity outputs.")
    governance_cols = st.columns(4)
    if curve_coverage_report_path.exists():
        coverage_df = read_csv_or_empty(curve_coverage_report_path)
        missing_curves = int((~coverage_df["has_curve"]).sum()) if "has_curve" in coverage_df.columns else 0
        governance_cols[0].metric("Observed Tags", f"{len(coverage_df):,}")
        governance_cols[1].metric("Missing Curves", f"{missing_curves:,}")
    if curve_monotonicity_report_path.exists():
        monotonicity_df = read_csv_or_empty(curve_monotonicity_report_path)
        severity = monotonicity_df["severity"].astype(str).str.lower() if "severity" in monotonicity_df.columns else pd.Series(dtype=str)
        governance_cols[2].metric("Curve Errors", f"{int((severity == 'error').sum()):,}")
        governance_cols[3].metric("Curve Warnings", f"{int((severity == 'warning').sum()):,}")

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
    failures_df = read_csv_or_empty(log_path, usecols=["timestamp", "reason_code"], nrows=50000)
    if failures_df.empty:
        st.info("No scrape failures recorded.")
    else:
        failures_df["timestamp"] = pd.to_datetime(failures_df["timestamp"], errors="coerce")
        reason_counts = failures_df["reason_code"].fillna("Unknown").value_counts().head(20)
        st.dataframe(reason_counts.reset_index(name="count"), use_container_width=True, hide_index=True)
else:
    st.info("excluded_listings.csv not found.")
