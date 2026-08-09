from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from shared.navigation import render_sidebar_navigation

from scripts.process_curve_candidates import (
    DEFAULT_AUTOTRADER_SOURCE,
    load_autotrader_market,
    run_autotrader_scrape,
    update_autotrader_queue_status,
)
from shared.csv_utils import CSV_READ_ERRORS
from shared.data_loader import dataset_path
from shared.styling import display_banner, hero_action_card, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Curve Pipeline", layout="wide")
render_sidebar_navigation()
inject_global_styles()
display_banner()
page_intro(
    "CURVE PIPELINE",
    "Candidate queue and Autotrader follow-up for curve lanes. Curve prices are edited only in Curve Builder V2.",
    show_logo=False,
)


CANDIDATE_PATH = dataset_path("quality/curve_candidates.csv")
BUILD_LOG_PATH = dataset_path("quality/curve_build_log.csv")
SCRAPE_QUEUE_PATH = dataset_path("quality/autotrader_scrape_queue.csv")
CURVES_PATH = dataset_path("curves.csv")
AUTOTRADER_SOURCE_PATH = DEFAULT_AUTOTRADER_SOURCE
SEED_URLS_PATH = Path("autotrader_isolated/output/curve_seed_urls.txt")
SCRAPE_OUTPUT_PATH = Path("autotrader_isolated/output/first_page_results_tagged.csv")
STORAGE_STATE_PATH = "autotrader_isolated/output/storage_state.json"
COOKIE_FILE_PATH = "autotrader_isolated/output/autotrader_cookie.txt"


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except CSV_READ_ERRORS as exc:
        st.warning(f"Could not read {path}: {type(exc).__name__}: {exc}")
        return pd.DataFrame()


def _last_write(path: Path) -> str:
    if not path.exists():
        return "never"
    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone()
    return ts.strftime("%Y-%m-%d %H:%M")


def _run_python_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, *args]
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _ready_candidates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "recommended_action" not in df.columns:
        return pd.DataFrame()
    actions = df["recommended_action"].fillna("").astype(str)
    return df[actions.isin(["build_curve", "refresh_curve"])].copy()


def _manual_review_candidates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "recommended_action" not in df.columns:
        return pd.DataFrame()
    actions = df["recommended_action"].fillna("").astype(str)
    return df[actions == "manual_review"].copy()


def _completed_scrapes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "status" not in df.columns:
        return pd.DataFrame()
    status = df["status"].fillna("").astype(str).str.lower()
    return df[status == "completed"].copy()


def _pending_scrapes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "status" not in df.columns:
        return pd.DataFrame()
    status = df["status"].fillna("").astype(str).str.lower()
    return df[status.isin(["queued", "failed", "running"])].copy()


def _display_result(result: subprocess.CompletedProcess[str], *, success_message: str) -> None:
    if result.returncode == 0:
        st.success(success_message)
    else:
        st.error(f"Command failed with exit code {result.returncode}.")
    if result.stdout.strip():
        st.code(result.stdout[-8000:], language="text")
    if result.stderr.strip():
        st.code(result.stderr[-4000:], language="text")


def _stash_result(result: subprocess.CompletedProcess[str], *, success_message: str) -> None:
    st.session_state["curve_pipeline_last_result"] = {
        "returncode": result.returncode,
        "success_message": success_message,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _latest_by_curve_tag(df: pd.DataFrame, *, timestamp_col: str) -> pd.DataFrame:
    if df.empty or "curve_tag" not in df.columns or timestamp_col not in df.columns:
        return pd.DataFrame()
    latest = df.copy()
    latest[timestamp_col] = pd.to_datetime(latest[timestamp_col], errors="coerce", utc=True)
    latest = latest.sort_values(timestamp_col, ascending=False)
    latest = latest.drop_duplicates(subset=["curve_tag"], keep="first")
    return latest.set_index("curve_tag", drop=False)


def _build_failure_note(row: pd.Series | None) -> str:
    if row is None or row.empty:
        return ""
    for column in ["notes", "last_result"]:
        value = row.get(column)
        if pd.notna(value) and str(value).strip():
            return str(value).strip()
    return ""


def _stage_label(stage_key: str) -> str:
    labels = {
        "manual_review": "Manual Review",
        "autotrader_completed": "Autotrader Completed",
        "autotrader_running": "Autotrader Running",
        "autotrader_queued": "Autotrader Queued",
        "autotrader_failed": "Autotrader Failed",
        "curve_saved": "Curve Saved",
        "validated": "Validated",
        "build_failed": "Build Failed",
        "ready_for_build": "Ready For Build",
        "candidate_discovered": "Candidate Discovered",
    }
    return labels.get(stage_key, stage_key.replace("_", " ").title())


def _resolve_current_stage(
    *,
    recommended_action: str,
    ready_for_curve: bool,
    review_reason: str,
    build_status: str,
    scrape_status: str,
) -> tuple[str, int, str, str]:
    build_status = build_status.strip().lower()
    scrape_status = scrape_status.strip().lower()
    review_reason = review_reason.strip()

    if scrape_status == "completed":
        return ("autotrader_completed", 8, "Curve and scrape are complete. Refresh on drift or schedule the next review.", "")
    if scrape_status == "running":
        return ("autotrader_running", 7, "Wait for the scraper to finish, then review listing deltas.", "")
    if scrape_status == "queued":
        return ("autotrader_queued", 6, "Run pending Autotrader scrapes.", "")
    if scrape_status == "failed":
        return ("autotrader_failed", 6, "Rerun the scraper and check the scrape result note.", "Autotrader scrape failed")
    if build_status == "saved":
        return ("curve_saved", 5, "Queue or run the Autotrader scrape for this tag.", "")
    if build_status == "validated":
        return ("validated", 4, "Persist the curve or continue to the scrape step.", "")
    if build_status in {"validation_failed", "ai_error"}:
        return ("build_failed", 3, "Retry the AI build with a stronger model or more timeout.", build_status.replace("_", " "))
    if recommended_action == "manual_review":
        if review_reason == "low_sample_size":
            next_move = "Lower the minimum listings gate or ingest more sold rows."
        elif "low_odometer_variance" in review_reason:
            next_move = "Add more sold rows with wider odometer coverage before building."
        else:
            next_move = "Inspect the rejected group before building."
        return ("manual_review", 1, next_move, review_reason or "Manual review required")
    if ready_for_curve:
        return ("ready_for_build", 2, "Run the AI curve build now.", "")
    return ("candidate_discovered", 0, "Refresh candidates after new sold data lands.", "")


def _build_stage_frame(
    candidates_df: pd.DataFrame,
    build_log_df: pd.DataFrame,
    scrape_queue_df: pd.DataFrame,
) -> pd.DataFrame:
    latest_build = _latest_by_curve_tag(build_log_df, timestamp_col="timestamp")
    latest_scrape = _latest_by_curve_tag(scrape_queue_df, timestamp_col="timestamp")
    tags: list[str] = []
    for df in [candidates_df, build_log_df, scrape_queue_df]:
        if not df.empty and "curve_tag" in df.columns:
            tags.extend(df["curve_tag"].dropna().astype(str).tolist())
    if not tags:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    candidate_indexed = candidates_df.set_index("curve_tag", drop=False) if not candidates_df.empty and "curve_tag" in candidates_df.columns else pd.DataFrame()
    for curve_tag in sorted(set(tags)):
        candidate_row = candidate_indexed.loc[curve_tag] if not candidate_indexed.empty and curve_tag in candidate_indexed.index else None
        if isinstance(candidate_row, pd.DataFrame):
            candidate_row = candidate_row.iloc[0]
        build_row = latest_build.loc[curve_tag] if not latest_build.empty and curve_tag in latest_build.index else None
        scrape_row = latest_scrape.loc[curve_tag] if not latest_scrape.empty and curve_tag in latest_scrape.index else None

        recommended_action = str(candidate_row.get("recommended_action", "") if candidate_row is not None else "").strip()
        ready_for_curve = _truthy(candidate_row.get("ready_for_curve") if candidate_row is not None else False)
        review_reason = str(candidate_row.get("review_reason", "") if candidate_row is not None else "").strip()
        build_status = str(build_row.get("result_status", "") if build_row is not None else "").strip()
        scrape_status = str(scrape_row.get("status", "") if scrape_row is not None else "").strip()
        stage_key, stage_order, next_move, blocker = _resolve_current_stage(
            recommended_action=recommended_action,
            ready_for_curve=ready_for_curve,
            review_reason=review_reason,
            build_status=build_status,
            scrape_status=scrape_status,
        )

        rows.append(
            {
                "curve_tag": curve_tag,
                "priority_rank": candidate_row.get("priority_rank") if candidate_row is not None else None,
                "stage_order": stage_order,
                "current_stage": _stage_label(stage_key),
                "recommended_action": recommended_action or None,
                "sold_count_usable": candidate_row.get("sold_count_usable") if candidate_row is not None else None,
                "score": candidate_row.get("score") if candidate_row is not None else None,
                "latest_build_status": build_status or None,
                "latest_scrape_status": scrape_status or None,
                "build_model": build_row.get("model") if build_row is not None else None,
                "confidence": build_row.get("confidence") if build_row is not None else None,
                "blocker": blocker or _build_failure_note(build_row if stage_key == "build_failed" else scrape_row),
                "next_move": next_move,
            }
        )

    stage_df = pd.DataFrame(rows)
    if stage_df.empty:
        return stage_df
    return stage_df.sort_values(["stage_order", "priority_rank", "curve_tag"], ascending=[False, True, True], na_position="last").reset_index(drop=True)


def _build_unlock_frame(manual_df: pd.DataFrame, *, current_min_listings: int) -> pd.DataFrame:
    if manual_df.empty:
        return pd.DataFrame()
    unlockable = manual_df.copy()
    unlockable["review_reason"] = unlockable["review_reason"].fillna("").astype(str)
    unlockable = unlockable[
        (unlockable["review_reason"] == "low_sample_size")
        & unlockable["passes_year_span"].fillna(False)
        & unlockable["passes_odometer_variance"].fillna(False)
    ].copy()
    if unlockable.empty or "sold_count_usable" not in unlockable.columns:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    thresholds = sorted(
        {
            int(value)
            for value in unlockable["sold_count_usable"].dropna().tolist()
            if int(value) < int(current_min_listings)
        },
        reverse=True,
    )
    for threshold in thresholds:
        unlocked = unlockable[unlockable["sold_count_usable"].fillna(0).astype(int) >= threshold].sort_values(
            ["sold_count_usable", "score"],
            ascending=[False, False],
        )
        rows.append(
            {
                "min_listings": threshold,
                "new_ready_count": len(unlocked),
                "curve_tags": ", ".join(unlocked["curve_tag"].astype(str).head(4).tolist()),
            }
        )
    return pd.DataFrame(rows)


def _step_status_frame(stage_row: pd.Series) -> pd.DataFrame:
    recommended_action = str(stage_row.get("recommended_action") or "").strip().lower()
    build_status = str(stage_row.get("latest_build_status") or "").strip().lower()
    scrape_status = str(stage_row.get("latest_scrape_status") or "").strip().lower()
    current_stage = str(stage_row.get("current_stage") or "").strip()

    gate_status = "blocked" if recommended_action == "manual_review" else "done"
    if current_stage in {"Ready For Build", "Candidate Discovered"}:
        gate_status = "current" if current_stage == "Ready For Build" else "pending"

    ai_status = "pending"
    if build_status in {"saved", "validated"}:
        ai_status = "done"
    elif build_status in {"validation_failed", "ai_error"}:
        ai_status = "failed"
    elif current_stage == "Ready For Build":
        ai_status = "current"

    save_status = "done" if build_status == "saved" else "pending"
    if build_status in {"validation_failed", "ai_error"}:
        save_status = "blocked"

    scrape_step_status = "pending"
    if scrape_status == "completed":
        scrape_step_status = "done"
    elif scrape_status in {"queued", "running"}:
        scrape_step_status = "current"
    elif scrape_status == "failed":
        scrape_step_status = "failed"
    elif build_status == "saved":
        scrape_step_status = "current"

    return pd.DataFrame(
        [
            {"step": "1. Candidate discovered", "status": "done", "detail": "Grouped from sold history and tagged canonically."},
            {"step": "2. Viability gate", "status": gate_status, "detail": stage_row.get("blocker") or stage_row.get("recommended_action") or "Passed conservative queue gates."},
            {"step": "3. AI build", "status": ai_status, "detail": stage_row.get("latest_build_status") or "No AI build attempt yet."},
            {"step": "4. Curve saved", "status": save_status, "detail": "Saved into governed curves only after validation passes."},
            {"step": "5. Autotrader scrape", "status": scrape_step_status, "detail": stage_row.get("latest_scrape_status") or "No scrape queued yet."},
        ]
    )


def _build_active_counts(active_df: pd.DataFrame) -> pd.Series:
    if active_df.empty or "curve_tag" not in active_df.columns:
        return pd.Series(dtype="int64")
    counts = active_df["curve_tag"].fillna("").astype(str).str.strip()
    counts = counts[counts.ne("")]
    return counts.value_counts().sort_index()


def _build_curve_exists_set(curves_df: pd.DataFrame) -> set[str]:
    if curves_df.empty or "canonical_tag" not in curves_df.columns:
        return set()
    return {
        str(value).strip()
        for value in curves_df["canonical_tag"].dropna().astype(str).tolist()
        if str(value).strip()
    }


def _build_make_summary(
    candidates_df: pd.DataFrame,
    active_counts: pd.Series,
    curves_present: set[str],
) -> pd.DataFrame:
    if candidates_df.empty or "make" not in candidates_df.columns:
        return pd.DataFrame()

    working = candidates_df.copy()
    working["make"] = working["make"].fillna("").astype(str).str.strip().str.lower()
    working["recommended_action"] = working["recommended_action"].fillna("").astype(str).str.strip()
    working["review_reason"] = working["review_reason"].fillna("").astype(str).str.strip()
    working["active_listing_count"] = (
        working["curve_tag"].fillna("").astype(str).map(active_counts).fillna(0).astype(int)
        if "curve_tag" in working.columns
        else 0
    )
    working["curve_saved"] = (
        working["curve_tag"].fillna("").astype(str).isin(curves_present)
        if "curve_tag" in working.columns
        else False
    )

    rows: list[dict[str, object]] = []
    for make_value, group in working.groupby("make", sort=True):
        review_counts = group[group["recommended_action"] == "manual_review"]["review_reason"].value_counts()
        rows.append(
            {
                "make": make_value or "unknown",
                "total_tags": int(len(group)),
                "ready_tags": int(group["recommended_action"].isin(["build_curve", "refresh_curve"]).sum()),
                "blocked_tags": int((group["recommended_action"] == "manual_review").sum()),
                "saved_curves": int(group["curve_saved"].sum()),
                "active_listings": int(group["active_listing_count"].sum()),
                "top_block_reason": str(review_counts.index[0]) if not review_counts.empty else "",
            }
        )
    return pd.DataFrame(rows).sort_values(["ready_tags", "active_listings", "total_tags"], ascending=[False, False, False]).reset_index(drop=True)


def _build_evidence_frame(
    candidates_df: pd.DataFrame,
    stage_df: pd.DataFrame,
    active_counts: pd.Series,
    curves_present: set[str],
) -> pd.DataFrame:
    if candidates_df.empty:
        return pd.DataFrame()

    working = candidates_df.copy()
    working["curve_tag"] = working["curve_tag"].fillna("").astype(str).str.strip()
    working["sold_count_usable"] = pd.to_numeric(working.get("sold_count_usable"), errors="coerce").fillna(0).astype(int)
    working["active_listing_count"] = working["curve_tag"].map(active_counts).fillna(0).astype(int)
    working["curve_saved"] = working["curve_tag"].isin(curves_present)
    if not stage_df.empty and "curve_tag" in stage_df.columns:
        stage_cols = [
            column
            for column in ["curve_tag", "current_stage", "latest_build_status", "latest_scrape_status", "next_move"]
            if column in stage_df.columns
        ]
        working = working.merge(stage_df[stage_cols], on="curve_tag", how="left")

    display_cols = [
        column
        for column in [
            "priority_rank",
            "make",
            "curve_tag",
            "sold_count_usable",
            "active_listing_count",
            "curve_saved",
            "recommended_action",
            "current_stage",
            "review_reason",
            "next_move",
        ]
        if column in working.columns
    ]
    return working[display_cols].sort_values(
        ["active_listing_count", "sold_count_usable", "priority_rank"],
        ascending=[False, False, True],
        na_position="last",
    ).reset_index(drop=True)


candidates_df = _load_csv(CANDIDATE_PATH)
build_log_df = _load_csv(BUILD_LOG_PATH)
scrape_queue_df = _load_csv(SCRAPE_QUEUE_PATH)
curves_df = _load_csv(CURVES_PATH)
active_market_df = load_autotrader_market(AUTOTRADER_SOURCE_PATH)

ready_df = _ready_candidates(candidates_df)
manual_df = _manual_review_candidates(candidates_df)
pending_scrape_df = _pending_scrapes(scrape_queue_df)
completed_scrape_df = _completed_scrapes(scrape_queue_df)
stage_df = _build_stage_frame(candidates_df, build_log_df, scrape_queue_df)
active_counts = _build_active_counts(active_market_df)
curves_present = _build_curve_exists_set(curves_df)
make_summary_df = _build_make_summary(candidates_df, active_counts, curves_present)
evidence_df = _build_evidence_frame(candidates_df, stage_df, active_counts, curves_present)

last_result = st.session_state.get("curve_pipeline_last_result")
if isinstance(last_result, dict):
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=int(last_result.get("returncode", 1)),
        stdout=str(last_result.get("stdout", "") or ""),
        stderr=str(last_result.get("stderr", "") or ""),
    )
    _display_result(completed, success_message=str(last_result.get("success_message", "Command completed.")))
    if st.button("Clear last run output", key="curve_pipeline_clear_last_result"):
        st.session_state.pop("curve_pipeline_last_result", None)
        st.rerun()

metric_cols = st.columns(5)
metric_cols[0].metric("Ready Curves", f"{len(ready_df):,}", delta=f"updated {_last_write(CANDIDATE_PATH)}")
metric_cols[1].metric("Manual Review", f"{len(manual_df):,}")
metric_cols[2].metric("Saved Curves", f"{curves_df['canonical_tag'].nunique() if 'canonical_tag' in curves_df.columns else 0:,}")
metric_cols[3].metric("Pending Scrapes", f"{len(pending_scrape_df):,}")
metric_cols[4].metric("Completed Scrapes", f"{len(completed_scrape_df):,}")

section_heading("Make Summary", "See which makes are ready, which are blocked, and where live market coverage already exists.")
if make_summary_df.empty:
    st.info("No make-level summary is available yet.")
else:
    st.dataframe(make_summary_df, use_container_width=True, hide_index=True)

section_heading("Pipeline Actions", "Refresh queue inputs and execute Autotrader follow-up. Curve pricing is handled in Curve Builder V2.")
action_cols = st.columns(2)
with action_cols[0]:
    refresh_clicked = hero_action_card(
        "Refresh Candidates",
        "Rebuild the sold-history queue from canonical tags and viability rules.",
        "Run candidate scan",
        button_key="curve_pipeline_refresh_candidates",
    )
with action_cols[1]:
    scrape_clicked = hero_action_card(
        "Run Scrapes",
        "Execute all pending Autotrader seed URLs and update queue status.",
        "Run pending scrapes",
        button_key="curve_pipeline_run_scrapes",
    )

section_heading("Queue Controls", "Set queue thresholds and Autotrader scrape scope.")
control_left, control_right = st.columns(2)
with control_left:
    min_listings = st.number_input("Min sold listings", min_value=1, max_value=200, value=20, step=1)
    max_year_span = st.number_input("Max year span", min_value=1, max_value=20, value=6, step=1)
    min_odometer_std = st.number_input("Min odometer std", min_value=0, max_value=200000, value=10000, step=1000)
with control_right:
    headful = st.checkbox("Headful scraper", value=True)

st.caption(
    "Conservative readiness still helps prioritize lane review, but this page no longer writes curve prices. "
    "Use Curve Builder V2 for Carsales/manual evidence-backed curve edits; use Autotrader here only for comparison follow-up."
)

unlock_df = _build_unlock_frame(manual_df, current_min_listings=int(min_listings))

section_heading("Stage Overview", "See the current pipeline stage for each tag and the quickest unlock path for new curves.")
stage_metric_cols = st.columns(5)
stage_metric_cols[0].metric(
    "Ready Now",
    f"{0 if stage_df.empty else int((stage_df['current_stage'] == 'Ready For Build').sum()):,}",
)
stage_metric_cols[1].metric(
    "Build Failed",
    f"{0 if stage_df.empty else int((stage_df['current_stage'] == 'Build Failed').sum()):,}",
)
stage_metric_cols[2].metric(
    "Saved Awaiting Scrape",
    f"{0 if stage_df.empty else int((stage_df['current_stage'] == 'Curve Saved').sum()):,}",
)
stage_metric_cols[3].metric(
    "Scrape Completed",
    f"{0 if stage_df.empty else int((stage_df['current_stage'] == 'Autotrader Completed').sum()):,}",
)
stage_metric_cols[4].metric(
    "Blocked",
    f"{0 if stage_df.empty else int((stage_df['current_stage'] == 'Manual Review').sum()):,}",
)

if unlock_df.empty:
    st.info("There are no immediate threshold-only unlocks in the current manual-review queue.")
else:
    fastest_unlock = unlock_df.iloc[0]
    st.warning(
        f"Fastest route to new curves: lower `Min listings` from {int(min_listings)} to {int(fastest_unlock['min_listings'])}. "
        f"That would unlock {int(fastest_unlock['new_ready_count'])} additional tags immediately."
    )
    st.dataframe(unlock_df.head(5), use_container_width=True, hide_index=True)

if stage_df.empty:
    st.info("No curve-stage data available yet.")
else:
    stage_display_cols = [
        column
        for column in [
            "priority_rank",
            "curve_tag",
            "current_stage",
            "sold_count_usable",
            "latest_build_status",
            "latest_scrape_status",
            "blocker",
            "next_move",
        ]
        if column in stage_df.columns
    ]
    st.dataframe(stage_df[stage_display_cols], use_container_width=True, hide_index=True)

    inspect_options = stage_df["curve_tag"].astype(str).tolist()
    default_inspect = inspect_options[0] if inspect_options else None
    inspect_curve_tag = st.selectbox("Inspect curve tag stage", options=inspect_options, index=0 if default_inspect else None)
    if inspect_curve_tag:
        inspect_row = stage_df[stage_df["curve_tag"] == inspect_curve_tag].iloc[0]
        inspect_left, inspect_right = st.columns([1, 1])
        with inspect_left:
            st.caption("Current stage")
            st.subheader(str(inspect_row["current_stage"]))
            st.write(str(inspect_row.get("next_move") or ""))
        with inspect_right:
            st.caption("Step status")
            st.dataframe(_step_status_frame(inspect_row), use_container_width=True, hide_index=True)

        tag_build_history = (
            build_log_df[build_log_df["curve_tag"].astype(str) == inspect_curve_tag].sort_values("timestamp", ascending=False)
            if not build_log_df.empty and "curve_tag" in build_log_df.columns
            else pd.DataFrame()
        )
        tag_scrape_history = (
            scrape_queue_df[scrape_queue_df["curve_tag"].astype(str) == inspect_curve_tag].sort_values("timestamp", ascending=False)
            if not scrape_queue_df.empty and "curve_tag" in scrape_queue_df.columns
            else pd.DataFrame()
        )
        history_left, history_right = st.columns(2)
        with history_left:
            st.caption("Build history")
            if tag_build_history.empty:
                st.info("No build attempts recorded for this tag.")
            else:
                st.dataframe(tag_build_history, use_container_width=True, hide_index=True)
        with history_right:
            st.caption("Scrape history")
            if tag_scrape_history.empty:
                st.info("No scrape history recorded for this tag.")
            else:
                st.dataframe(tag_scrape_history, use_container_width=True, hide_index=True)

section_heading("Evidence By Tag", "This shows the actual evidence currently available before changing any curve rules.")
if evidence_df.empty:
    st.info("No evidence view is available yet.")
else:
    st.dataframe(evidence_df, use_container_width=True, hide_index=True)

if refresh_clicked:
    result = _run_python_command(
        [
            "scripts/generate_curve_candidates.py",
            "--output",
            str(CANDIDATE_PATH),
            "--min-listings",
            str(int(min_listings)),
            "--max-year-span",
            str(int(max_year_span)),
            "--min-odometer-std",
            str(int(min_odometer_std)),
        ]
    )
    _stash_result(result, success_message="Candidate queue refreshed.")
    st.rerun()

if scrape_clicked:
    if pending_scrape_df.empty:
        st.info("No pending scrape URLs in the queue.")
    else:
        urls = pending_scrape_df["seed_url"].dropna().astype(str).str.strip().tolist()
        SEED_URLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SEED_URLS_PATH.write_text("\n".join(urls) + "\n", encoding="utf-8")
        result = run_autotrader_scrape(
            urls_file=SEED_URLS_PATH,
            output_path=SCRAPE_OUTPUT_PATH,
            storage_state=STORAGE_STATE_PATH,
            cookie_file=COOKIE_FILE_PATH,
            browser="chrome",
            wait_mode="load",
            block_resources=False,
            headful=headful,
        )
        status = "completed" if result.returncode == 0 else "failed"
        note = (result.stdout or "").strip()[-1000:]
        if result.stderr:
            note = f"{note}\n{result.stderr.strip()[-500:]}".strip()
        update_autotrader_queue_status(
            SCRAPE_QUEUE_PATH,
            seed_urls=urls,
            status=status,
            result_note=note or "Autotrader scrape run from Curve Pipeline page.",
        )
        _stash_result(result, success_message="Pending Autotrader scrapes completed.")
        st.rerun()

queue_tab, log_tab, scrape_tab = st.tabs(["Candidate Queue", "Build Log", "Scrape Queue"])

with queue_tab:
    section_heading("Ready Queue", "Tags that can go straight into the curve builder.")
    if ready_df.empty:
        st.info("No ready curve candidates yet.")
    else:
        display_cols = [
            column
            for column in [
                "priority_rank",
                "curve_tag",
                "recommended_action",
                "sold_count_usable",
                "score",
                "year_min",
                "year_max",
                "source_canonical_tags",
                "autotrader_query",
            ]
            if column in ready_df.columns
        ]
        st.dataframe(ready_df[display_cols], use_container_width=True, hide_index=True)

    section_heading("Manual Review", "Groups that failed the conservative gates.")
    if manual_df.empty:
        st.info("No manual-review items in the current queue.")
    else:
        review_cols = [
            column
            for column in [
                "priority_rank",
                "curve_tag",
                "review_reason",
                "sold_count_usable",
                "score",
                "source_canonical_tags",
            ]
            if column in manual_df.columns
        ]
        st.dataframe(manual_df[review_cols], use_container_width=True, hide_index=True)

with log_tab:
    section_heading("Recent Curve Jobs", "Validation failures and saved curves are recorded here.")
    if build_log_df.empty:
        st.info("No curve build log entries yet.")
    else:
        st.dataframe(build_log_df.sort_values("timestamp", ascending=False), use_container_width=True, hide_index=True)

with scrape_tab:
    section_heading("Pending Scrapes", "Autotrader follow-up that has not been marked completed.")
    if pending_scrape_df.empty:
        st.success("No pending scrape jobs.")
    else:
        st.dataframe(pending_scrape_df.sort_values("timestamp", ascending=False), use_container_width=True, hide_index=True)

    section_heading("Scrape History", "Completed or failed queue runs.")
    if scrape_queue_df.empty:
        st.info("No scrape queue history yet.")
    else:
        st.dataframe(scrape_queue_df.sort_values("timestamp", ascending=False), use_container_width=True, hide_index=True)
