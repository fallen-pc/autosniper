from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from shared.navigation import render_sidebar_navigation
from shared.repair_ai_classifier import AI_SUGGESTIONS_PATH, load_ai_suggestions
from shared.repair_monitor import build_printable_repair_html, build_repair_monitor_rows, repair_monitor_summary
from shared.repair_review import DECISIONS_PATH, LIVE_QUEUE_PATH, latest_repair_decisions
from shared.styling import display_banner, inject_global_styles, page_intro


st.set_page_config(page_title="Repair Monitor", layout="wide")
render_sidebar_navigation()
inject_global_styles()
display_banner()
page_intro(
    "REPAIR MONITOR",
    "Track priced repairs, hard avoids, unresolved descriptions, and Astra review activity from the live runtime.",
    show_logo=False,
)

RUN_STATUS_PATH = Path("CSV_data/reports/repair_ai_run_status.json")
RUN_HISTORY_PATH = Path("CSV_data/reports/repair_ai_run_history.csv")


@st.cache_data(ttl=60)
def load_monitor_rows() -> pd.DataFrame:
    if not LIVE_QUEUE_PATH.exists():
        return pd.DataFrame()
    queue = pd.read_csv(LIVE_QUEUE_PATH).fillna("")
    suggestions = load_ai_suggestions(AI_SUGGESTIONS_PATH)
    decisions = pd.read_csv(DECISIONS_PATH).fillna("") if DECISIONS_PATH.exists() else pd.DataFrame()
    decisions = latest_repair_decisions(decisions)
    return build_repair_monitor_rows(queue, suggestions, decisions)


@st.cache_data(ttl=60)
def load_run_status() -> dict[str, object]:
    if not RUN_STATUS_PATH.exists():
        return {}
    try:
        return json.loads(RUN_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@st.cache_data(ttl=60)
def load_run_history() -> pd.DataFrame:
    if not RUN_HISTORY_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(RUN_HISTORY_PATH).fillna("")
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return pd.DataFrame()


rows = load_monitor_rows()
if rows.empty:
    st.error("The live Repair Review queue is unavailable.")
    st.stop()

summary = repair_monitor_summary(rows)
metric_top = st.columns(3)
metric_top[0].metric("Repair lines", f"{summary['total']:,}")
metric_top[1].metric("Priced", f"{summary['priced']:,}")
metric_top[2].metric("Needs decision", f"{summary['unpriced']:,}")
metric_bottom = st.columns(3)
metric_bottom[0].metric("Hard avoids", f"{summary['hard_avoid']:,}")
metric_bottom[1].metric("No-cost context", f"{summary['ignored']:,}")
metric_bottom[2].metric("Astra pending", f"{summary['ai_pending']:,}")

st.caption(
    "Amounts are reference estimates from the deployed repair schedule. Vehicle-level valuation can adjust them by class and severity. "
    "Astra suggestions remain advisory until an operator-approved rule is deployed."
)

download_left, download_right, status_column = st.columns([1, 1, 2])
with download_left:
    st.download_button(
        "Download current repairs CSV",
        data=rows.to_csv(index=False),
        file_name="autosniper_current_repairs.csv",
        mime="text/csv",
        width="stretch",
    )
with download_right:
    st.download_button(
        "Download printable report",
        data=build_printable_repair_html(rows),
        file_name="autosniper_current_repairs.html",
        mime="text/html",
        width="stretch",
    )
with status_column:
    status = load_run_status()
    if status:
        st.info(
            f"Latest Astra check: {status.get('finished_at_utc', 'unknown')} | "
            f"{status.get('status', 'unknown')} | considered {status.get('considered', 0)} | "
            f"suggested {status.get('suggested', 0)} | model {status.get('model', 'unknown')}"
        )
    else:
        st.info("No classifier run has been recorded yet. Activity will appear after the next scheduled check.")

st.sidebar.markdown("### Repair filters")
search = st.sidebar.text_input("Search repair text")
minimum_occurrences = st.sidebar.number_input("Minimum occurrences", min_value=1, value=1, step=1)
outcome_filter = st.sidebar.multiselect("Outcomes", options=list(rows["outcome"].drop_duplicates()), default=[])

filtered = rows[rows["occurrences"] >= int(minimum_occurrences)].copy()
if search.strip():
    needle = search.strip().lower()
    filtered = filtered[
        filtered["repair_item"].str.lower().str.contains(needle, regex=False)
        | filtered["canonical_defects"].str.lower().str.contains(needle, regex=False)
        | filtered["ai_canonical_defect"].str.lower().str.contains(needle, regex=False)
    ]
if outcome_filter:
    filtered = filtered[filtered["outcome"].isin(outcome_filter)]

DISPLAY_COLUMNS = [
    "repair_item",
    "occurrences",
    "listing_count",
    "default_cost",
    "low_cost",
    "high_cost",
    "canonical_defects",
    "ai_decision",
    "ai_canonical_defect",
    "ai_confidence",
    "operator_state",
]
COLUMN_CONFIG = {
    "repair_item": "Repair description",
    "occurrences": st.column_config.NumberColumn("Occurrences", format="%d"),
    "listing_count": st.column_config.NumberColumn("Listings", format="%d"),
    "default_cost": st.column_config.NumberColumn("Default", format="$%d"),
    "low_cost": st.column_config.NumberColumn("Low", format="$%d"),
    "high_cost": st.column_config.NumberColumn("High", format="$%d"),
    "canonical_defects": "Current repair type",
    "ai_decision": "Astra suggestion",
    "ai_canonical_defect": "Astra repair type",
    "ai_confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
    "operator_state": "Approval",
}


def show_table(frame: pd.DataFrame, *, empty_message: str) -> None:
    if frame.empty:
        st.success(empty_message)
        return
    st.dataframe(
        frame[DISPLAY_COLUMNS],
        width="stretch",
        hide_index=True,
        column_config=COLUMN_CONFIG,
        height=min(720, 38 + 35 * min(len(frame), 19)),
    )


action_tab, priced_tab, avoid_tab, all_tab, activity_tab = st.tabs(
    ["Needs Decision", "Priced", "Hard Avoids", "All Repairs", "Astra Activity"]
)
with action_tab:
    action_rows = filtered[filtered["outcome"] == "Needs decision"]
    st.markdown(f"### Action required ({len(action_rows):,})")
    st.caption("These descriptions remain unpriced and cannot support a clean Buy until an operator approves a rule or holds them unresolved.")
    show_table(action_rows, empty_message="No unresolved repairs match the current filters.")
    if not action_rows.empty:
        action_labels = [
            f"{row.repair_item} [{int(row.occurrences):,} occurrence(s)]"
            for row in action_rows.itertuples(index=False)
        ]
        selected_label = st.selectbox("Inspect unresolved repair", action_labels)
        selected = action_rows.iloc[action_labels.index(selected_label)]
        detail_left, detail_right = st.columns(2)
        with detail_left:
            st.markdown("**Current parser result**")
            st.write(selected["unresolved_fragments"] or "No priced repair mapping")
            st.markdown("**Example vehicles**")
            st.write(selected["example_vehicles"] or "No vehicle example recorded")
        with detail_right:
            st.markdown("**Astra recommendation**")
            st.write(
                f"{selected['ai_decision'] or 'Pending'} | "
                f"{selected['ai_canonical_defect'] or 'No canonical repair type'} | "
                f"confidence {selected['ai_confidence'] if not pd.isna(selected['ai_confidence']) else 'not available'}"
            )
            st.markdown("**Astra rationale**")
            st.write(selected["ai_rationale"] or "No rationale recorded")

with priced_tab:
    priced_rows = filtered[filtered["outcome"] == "Priced"]
    st.markdown(f"### Priced repairs ({len(priced_rows):,})")
    st.caption("The pessimistic high estimate is used when deducting repairs from a maximum bid.")
    show_table(priced_rows, empty_message="No priced repairs match the current filters.")

with avoid_tab:
    avoid_rows = filtered[filtered["outcome"] == "Hard avoid"]
    st.markdown(f"### Hard avoids ({len(avoid_rows):,})")
    st.caption("Any one of these conditions prevents an executable purchase recommendation.")
    show_table(avoid_rows, empty_message="No hard avoids match the current filters.")

with all_tab:
    st.markdown(f"### Complete current register ({len(filtered):,})")
    all_columns = ["outcome", *DISPLAY_COLUMNS]
    st.dataframe(
        filtered[all_columns],
        width="stretch",
        hide_index=True,
        column_config={"outcome": "Current outcome", **COLUMN_CONFIG},
        height=720,
    )

with activity_tab:
    history = load_run_history()
    if history.empty:
        st.info("Classifier activity will be recorded after the next scheduled check.")
    else:
        st.dataframe(history.tail(50).iloc[::-1], width="stretch", hide_index=True)

st.caption("This page is read-only. Approvals remain part of the tested and governed Repair Review release workflow.")
