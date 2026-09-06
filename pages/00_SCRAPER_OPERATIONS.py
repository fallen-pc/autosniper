from __future__ import annotations

import inspect

import pandas as pd
import streamlit as st

from shared.navigation import render_sidebar_navigation
from shared.scraper_operations import build_scraper_operations_snapshot
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="AutoSniper - Scraper Operations", layout="wide")

# Current navigation work renders links inside each page; the committed VPS
# navigation renders them once from app.py. Support both without duplication.
if not inspect.signature(render_sidebar_navigation).parameters:
    render_sidebar_navigation()

inject_global_styles()
display_banner()
page_intro(
    "SCRAPER OPERATIONS",
    "Live collection health, coverage, schedules, and failure signals.",
    show_logo=False,
)

snapshot = build_scraper_operations_snapshot()

st.markdown(
    """
    <style>
    .scraper-status-line {
        display: flex;
        align-items: center;
        gap: 0.65rem;
        margin: 0.2rem 0 1.1rem;
        color: rgba(229, 229, 229, 0.72);
    }
    .scraper-status-pill {
        display: inline-flex;
        align-items: center;
        padding: 0.28rem 0.7rem;
        border-radius: 999px;
        border: 1px solid rgba(39, 182, 255, 0.38);
        background: rgba(39, 182, 255, 0.10);
        color: #d9f4ff;
        font-size: 0.78rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    (
        '<div class="scraper-status-line">'
        f'<span class="scraper-status-pill">{snapshot["overall_status"]}</span>'
        f'<span>Snapshot generated {snapshot["generated_at"]}</span>'
        "</div>"
    ),
    unsafe_allow_html=True,
)

summary_cols = st.columns(5)
summary_cols[0].metric("System", snapshot["overall_status"])
summary_cols[1].metric("Latest daily run", snapshot["last_daily_status"])
summary_cols[2].metric("Active listings", f'{snapshot["active_listings"]:,}')
summary_cols[3].metric("Last duration", f'{snapshot["last_duration_minutes"]:.1f} min')
summary_cols[4].metric("Failed runs", f'{snapshot["runs_failed"]:,} / {snapshot["runs_total"]:,}')

schedule_cols = st.columns(4)
schedule_cols[0].metric("Last completed", snapshot["last_daily_run"])
schedule_cols[1].metric("Next scheduled", snapshot["next_daily_run"])
schedule_cols[2].metric("Next hourly monitor", snapshot["next_hourly_run"])
schedule_cols[3].metric("Running job", snapshot["running_job"] or "None")

if snapshot["last_error"]:
    st.warning(snapshot["last_error"])

section_heading("Source Health", "What each scraper produced and whether its output is current.")
source_df = pd.DataFrame(snapshot["source_rows"])
display_df = source_df.rename(
    columns={
        "source": "Source",
        "status": "Status",
        "detail": "Signal",
        "last_output": "Last output",
        "discovered": "Discovered",
        "parsed": "Parsed",
        "curve_matches": "Curve matches",
        "priced": "Priced",
        "errors": "Errors",
    }
)
display_columns = [
    "Source",
    "Status",
    "Signal",
    "Last output",
    "Discovered",
    "Parsed",
    "Curve matches",
    "Priced",
    "Errors",
]
st.dataframe(
    display_df[display_columns],
    width="stretch",
    hide_index=True,
    column_config={
        "Discovered": st.column_config.NumberColumn(format="%d"),
        "Parsed": st.column_config.NumberColumn(format="%d"),
        "Curve matches": st.column_config.NumberColumn(format="%d"),
        "Priced": st.column_config.NumberColumn(format="%d"),
        "Errors": st.column_config.NumberColumn(format="%d"),
    },
)

section_heading("Operations", "Read-only shortcuts to investigation and buying screens.")
link_cols = st.columns(3)
with link_cols[0]:
    st.page_link("pages/6_AI_ANALYSIS.py", label="Open AI Analysis", icon=":material/analytics:")
with link_cols[1]:
    st.page_link("pages/05_HEALTH.py", label="Open Pipeline Health", icon=":material/monitor_heart:")
with link_cols[2]:
    st.page_link("pages/12_GRAYS_PIPELINE.py", label="Open Grays Pipeline", icon=":material/directions_car:")

st.caption(
    "This public screen is deliberately read-only. Scraper starts, restarts, credentials, "
    "and session renewal remain server-side operations."
)
