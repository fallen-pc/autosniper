import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import streamlit as st

from shared.csv_utils import read_csv_or_empty
from shared.data_loader import dataset_path
from shared.schema import STATIC_VEHICLE_SCHEMA
from shared.curves import list_curve_tags, load_curves
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro


st.set_page_config(page_title="GRAYS PIPELINE", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "GRAYS PIPELINE",
    "End-to-end visibility from link extraction to active vehicle details.",
    show_logo=False,
)

st.markdown(
    clean_html(
        """
        <style>
        .pipeline-shell {
            display: grid;
            gap: 1rem;
            margin-bottom: 1.25rem;
        }
        .pipeline-diagram {
            display: grid;
            gap: 0.8rem;
            justify-items: center;
            margin-top: 0.8rem;
        }
        .pipeline-arrow {
            color: var(--autosniper-muted);
            font-size: 1.2rem;
            line-height: 1;
        }
        .pipeline-node {
            width: min(100%, 340px);
            background: linear-gradient(160deg, rgba(9, 19, 28, 0.96) 0%, rgba(15, 22, 34, 0.94) 100%);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 0.9rem 1rem;
            box-shadow: 0 14px 30px rgba(0, 0, 0, 0.28);
        }
        .pipeline-node.is-selected {
            border-color: rgba(31, 166, 255, 0.9);
            box-shadow: 0 0 0 1px rgba(31, 166, 255, 0.35), 0 20px 34px rgba(12, 139, 235, 0.2);
            transform: translateY(-1px);
        }
        .pipeline-node-step {
            font-size: 0.74rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: var(--autosniper-accent);
            margin-bottom: 0.25rem;
        }
        .pipeline-node-title {
            font-size: 1rem;
            font-weight: 700;
            color: var(--autosniper-primary);
        }
        .pipeline-node-subtitle {
            font-size: 0.84rem;
            color: var(--autosniper-muted);
            margin-top: 0.15rem;
        }
        .pipeline-selector-note {
            color: var(--autosniper-muted);
            font-size: 0.9rem;
            margin-top: 0.35rem;
        }
        .pipeline-panel {
            padding: 1.15rem 1.25rem 1.3rem;
        }
        .pipeline-panel-header {
            display: grid;
            gap: 0.25rem;
            margin-bottom: 0.9rem;
        }
        .pipeline-panel-kicker {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            color: var(--autosniper-accent);
        }
        .pipeline-panel-title {
            font-size: 1.3rem;
            font-weight: 700;
            color: var(--autosniper-primary);
        }
        .pipeline-panel-copy {
            color: var(--autosniper-muted);
            max-width: 70ch;
        }
        .pipeline-subsection-title {
            font-size: 0.76rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: var(--autosniper-muted);
            margin: 0.9rem 0 0.5rem;
        }
        .pipeline-rules {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            padding: 0.9rem 1rem;
        }
        .pipeline-rules ul {
            margin: 0;
            padding-left: 1rem;
        }
        .pipeline-rules li {
            margin: 0.3rem 0;
            color: var(--autosniper-primary-dark);
        }
        .pipeline-stage {
            background: linear-gradient(160deg, rgba(26, 33, 48, 0.96) 0%, rgba(18, 23, 36, 0.92) 100%);
            border: 1px solid var(--autosniper-border);
            box-shadow: 0 16px 36px rgba(0, 0, 0, 0.28);
        }
        .pipeline-stage .section-title {
            color: var(--autosniper-primary);
        }
        .pipeline-stage .section-subtitle {
            color: var(--autosniper-muted);
        }
        .pipeline-block {
            background: linear-gradient(160deg, #05070b 0%, #0b0f14 100%);
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 16px 36px rgba(0, 0, 0, 0.4);
        }
        .pipeline-block .section-title {
            color: #f2f6ff;
        }
        .pipeline-block .section-subtitle {
            color: rgba(255, 255, 255, 0.6);
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)


def _format_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _safe_read_csv(path: Path) -> pd.DataFrame:
    return read_csv_or_empty(path)


def _schema_table(columns: Iterable[str]) -> pd.DataFrame:
    return pd.DataFrame({"column": list(columns)})


def _normalise_rule_lines() -> list[str]:
    return [
        "- Remove compliance slugs and compliance notes from URLs and condition text.",
        "- Normalize make/model casing and strip compliance markers.",
        "- Normalize fuel type (petrol/diesel/hybrid/electric mapping).",
        "- Normalize transmission (auto/manual/CVT).",
        "- Clean odometer and engine capacity formats.",
        "- Normalize rego expiry + fallback to Unregistered.",
        "- Remove transmission/fuel/seat/cert notes from variant.",
        "- Apply body type alias rules based on variant text.",
    ]


def _exclusion_rule_lines() -> list[str]:
    return [
        "- Drop missing/invalid URL or non-HTTP URL.",
        "- Drop non-vehicle listings (motorcycles, trailers, boats).",
        "- Drop missing or out-of-range year.",
        "- Drop missing make/model/body/fuel/transmission/location.",
        "- Drop missing/invalid odometer (range + suspect checks).",
        "- Drop bad VIN when present.",
        "- Enforce allowed body types list.",
    ]


def _run_stage_command(args: list[str], *, spinner_text: str, success_text: str) -> None:
    with st.spinner(spinner_text):
        result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode == 0:
        st.success(success_text)
    else:
        st.error(f"Stage failed (exit code {result.returncode}).")
    if result.stdout.strip() or result.stderr.strip():
        with st.expander("Stage output", expanded=False):
            if result.stdout.strip():
                st.code(result.stdout, language="text")
            if result.stderr.strip():
                st.code(result.stderr, language="text")


def _file_summary(path: Path) -> dict[str, str]:
    if not path.exists():
        return {
            "status": "Missing",
            "rows": "0",
            "columns": "0",
            "modified": "-",
        }
    df = _safe_read_csv(path)
    modified = _format_ts(path.stat().st_mtime)
    return {
        "status": "Present",
        "rows": f"{len(df):,}",
        "columns": f"{df.shape[1]:,}",
        "modified": modified,
    }


def _render_dataset_summary_row(title: str, filename: str) -> None:
    summary = _file_summary(dataset_path(filename))
    st.markdown(
        clean_html(
            f"""
            <div class="autosniper-section pipeline-stage">
                <div class="section-title">{title}</div>
                <div class="section-subtitle">{filename}</div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Status", summary["status"])
    col_b.metric("Rows", summary["rows"])
    col_c.metric("Columns", summary["columns"])
    col_d.metric("Last modified", summary["modified"])


def _render_stage_header(step_label: str, title: str, subtitle: str) -> None:
    st.markdown(
        clean_html(
            f"""
            <div class="autosniper-section pipeline-stage pipeline-panel">
                <div class="pipeline-panel-header">
                    <div class="pipeline-panel-kicker">{step_label}</div>
                    <div class="pipeline-panel-title">{title}</div>
                    <div class="pipeline-panel-copy">{subtitle}</div>
                </div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


def _render_rules_block(title: str, lines: Iterable[str]) -> None:
    bullet_items = "".join(f"<li>{line.lstrip('- ').strip()}</li>" for line in lines if str(line).strip())
    st.markdown(
        clean_html(
            f"""
            <div class="pipeline-subsection-title">{title}</div>
            <div class="pipeline-rules">
                <ul>{bullet_items}</ul>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


def _render_schema_audit_block(*, show_header: bool = True) -> None:
    expected = {
        "raw_vehicle_data.csv": list(STATIC_VEHICLE_SCHEMA),
        "normalised_data.csv": list(STATIC_VEHICLE_SCHEMA),
        "vehicle_static_details.csv": list(
            dict.fromkeys(list(STATIC_VEHICLE_SCHEMA) + ["canonical_tag", "canonical_reason"])
        ),
    }
    rows: list[dict[str, str]] = []
    for filename, required_columns in expected.items():
        path = dataset_path(filename)
        if not path.exists():
            rows.append(
                {
                    "dataset": filename,
                    "status": "MISSING",
                    "expected_columns": str(len(required_columns)),
                    "actual_columns": "0",
                    "schema_match": "NO",
                }
            )
            continue
        df = _safe_read_csv(path)
        actual_columns = list(df.columns)
        rows.append(
            {
                "dataset": filename,
                "status": "PRESENT",
                "expected_columns": str(len(required_columns)),
                "actual_columns": str(len(actual_columns)),
                "schema_match": "YES" if actual_columns == required_columns else "NO",
            }
        )
    if show_header:
        block_html = clean_html(
            """
            <div class="autosniper-section pipeline-block">
                <div class="section-title">Schema Lock Audit</div>
                <div class="section-subtitle">Raw, normalised, and static schemas must match exactly.</div>
            </div>
            """
        )
        st.markdown(block_html, unsafe_allow_html=True)
    audit_df = pd.DataFrame(rows)
    st.dataframe(audit_df, use_container_width=True, hide_index=True)


def render_stage_1_panel() -> None:
    _render_stage_header(
        "Stage 1",
        "Links",
        "Collect the raw Grays listing URLs that seed the rest of the pipeline.",
    )
    if st.button("Run: Scrape Links", key="panel_stage1_run"):
        _run_stage_command(
            [sys.executable, "scripts/extract_links.py"],
            spinner_text="Running link scraper...",
            success_text="Link scraping completed.",
        )
    _render_rules_block(
        "Rules",
        [
            "- Crawl Grays search results and lot pages.",
            "- Store the full queue in all_vehicle_links.csv.",
            "- Maintain active_vehicle_links.csv as the working intake subset.",
        ],
    )
    st.markdown('<div class="pipeline-subsection-title">Dataset Summary</div>', unsafe_allow_html=True)
    _render_dataset_summary_row("All Vehicle Links", "all_vehicle_links.csv")
    _render_dataset_summary_row("Active Link Queue", "active_vehicle_links.csv")
    with st.expander("Preview tables", expanded=False):
        for fname in ["all_vehicle_links.csv", "active_vehicle_links.csv"]:
            st.markdown(f"### {fname}")
            path = dataset_path(fname)
            if path.exists():
                st.dataframe(_safe_read_csv(path).head(50), use_container_width=True, hide_index=True)
            else:
                st.info("Missing.")


def render_stage_2_panel() -> None:
    _render_stage_header(
        "Stage 2",
        "Details",
        "Extract raw vehicle attributes from each queued Grays listing before cleanup.",
    )
    if st.button("Run: Scrape Details", key="panel_stage2_run"):
        _run_stage_command(
            [sys.executable, "scripts/extract_vehicle_details.py", "--raw-only"],
            spinner_text="Running detail scrape...",
            success_text="Detail scraping completed.",
        )
    st.markdown('<div class="pipeline-subsection-title">Dataset Summary</div>', unsafe_allow_html=True)
    _render_dataset_summary_row("Raw Vehicle Data", "raw_vehicle_data.csv")
    _render_rules_block(
        "Rules",
        [
            "- Capture the raw listing payload before normalisation.",
            "- Preserve original field values for auditability.",
            "- Keep schema aligned with STATIC_VEHICLE_SCHEMA.",
        ],
    )
    with st.expander("Schema + Preview", expanded=False):
        st.dataframe(_schema_table(STATIC_VEHICLE_SCHEMA), use_container_width=True, hide_index=True)
        st.dataframe(
            _safe_read_csv(dataset_path("raw_vehicle_data.csv")).head(50),
            use_container_width=True,
            hide_index=True,
        )


def render_stage_3_panel() -> None:
    _render_stage_header(
        "Stage 3",
        "Normalise",
        "Standardise vehicle fields so exclusions, tagging, and valuation run on consistent inputs.",
    )
    if st.button("Run: Normalise", key="panel_stage3_run"):
        _run_stage_command(
            [sys.executable, "scripts/pipeline_stages.py", "normalize"],
            spinner_text="Running normalisation stage...",
            success_text="Normalisation completed.",
        )
    st.markdown('<div class="pipeline-subsection-title">Dataset Summary</div>', unsafe_allow_html=True)
    _render_dataset_summary_row("Normalised Data", "normalised_data.csv")
    _render_rules_block("Rules", _normalise_rule_lines())
    with st.expander("Preview tables", expanded=False):
        st.dataframe(
            _safe_read_csv(dataset_path("normalised_data.csv")).head(50),
            use_container_width=True,
            hide_index=True,
        )


def render_stage_4_panel() -> None:
    _render_stage_header(
        "Stage 4",
        "Exclude",
        "Remove out-of-policy or malformed records and produce the static canonical-ready dataset.",
    )
    if st.button("Run: Exclusions", key="panel_stage4_run"):
        _run_stage_command(
            [sys.executable, "scripts/pipeline_stages.py", "exclude"],
            spinner_text="Applying exclusion rules...",
            success_text="Exclusion stage completed.",
        )
    st.markdown('<div class="pipeline-subsection-title">Dataset Summary</div>', unsafe_allow_html=True)
    _render_dataset_summary_row("Excluded Listings", "excluded_listings.csv")
    _render_dataset_summary_row("Static Vehicle Details", "vehicle_static_details.csv")

    excluded_df = _safe_read_csv(dataset_path("excluded_listings.csv"))
    normal_df = _safe_read_csv(dataset_path("normalised_data.csv"))
    static_df = _safe_read_csv(dataset_path("vehicle_static_details.csv"))
    excluded_this_run = 0
    if not excluded_df.empty and "timestamp" in excluded_df.columns:
        ts_series = pd.to_datetime(excluded_df["timestamp"], errors="coerce")
        latest_ts = ts_series.max()
        if pd.notna(latest_ts):
            excluded_this_run = int((ts_series == latest_ts).sum())
    written_from_normalised = max(len(normal_df) - excluded_this_run, 0)
    metric_col_a, metric_col_b, metric_col_c = st.columns(3)
    metric_col_a.metric("Excluded (this run)", f"{excluded_this_run:,}")
    metric_col_b.metric("Written to static", f"{written_from_normalised:,}")
    metric_col_c.metric("Static total rows", f"{len(static_df):,}")

    _render_rules_block("Rules", _exclusion_rule_lines())
    with st.expander("Preview tables", expanded=False):
        if excluded_df.empty:
            st.info("excluded_listings.csv is empty.")
        else:
            table_df = excluded_df.copy().reset_index(drop=True)
            table_df.insert(0, "row_id", table_df.index + 1)
            st.dataframe(table_df.tail(200), use_container_width=True, hide_index=True)


def render_stage_5_panel() -> None:
    _render_stage_header(
        "Stage 5",
        "Canonical",
        "Map normalised records onto supported canonical tags and show the live curve universe.",
    )
    if st.button("Run: Match Canonical Tags", key="panel_stage5_run"):
        _run_stage_command(
            [sys.executable, "scripts/pipeline_stages.py", "match"],
            spinner_text="Running canonical match...",
            success_text="Canonical match completed.",
        )
    st.markdown('<div class="pipeline-subsection-title">Dataset Summary</div>', unsafe_allow_html=True)
    _render_dataset_summary_row("Matched Canonical", "matched_canonical_details.csv")
    _render_dataset_summary_row("Unmatched Canonical", "unmatched_canonical_details.csv")
    _render_rules_block(
        "Rules",
        [
            "- Match make/model/body/fuel/transmission against allowed variants.",
            "- Use badge aliases and series codes to disambiguate trims.",
            "- Fail closed to unmatched when policy checks do not pass.",
        ],
    )

    curves_df = load_curves()
    available_tags = sorted(list_curve_tags(curves_df))
    with st.expander("Available canonical tags", expanded=False):
        st.metric("Available tags", f"{len(available_tags):,}")
        if available_tags:
            st.dataframe(
                pd.DataFrame({"canonical_tag": available_tags}),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No tags found in curves.csv.")


def render_stage_6_panel() -> None:
    _render_stage_header(
        "Stage 6",
        "Active Listings",
        "Refresh bidding/status data and roll records into active, sold, and referred outputs.",
    )
    col_a, col_b = st.columns(2)
    if col_a.button("Run: Update Bids", key="panel_stage6_bids_run"):
        _run_stage_command(
            [sys.executable, "scripts/update_bids.py", "--limit", "25", "--batch-interval", "5", "--skip-master"],
            spinner_text="Refreshing active bid/status data...",
            success_text="Active bid/status refresh completed.",
        )
    if col_b.button("Run: Update Master", key="panel_stage6_master_run"):
        _run_stage_command(
            [sys.executable, "scripts/update_master.py"],
            spinner_text="Sorting active, sold, and referred datasets...",
            success_text="Master update completed.",
        )
    _render_rules_block(
        "Rules",
        [
            "- Update live bids and countdowns for active lots.",
            "- Promote ended lots into sold or referred outputs.",
            "- Feed downstream restricted builds and AI analysis inputs.",
        ],
    )
    st.markdown('<div class="pipeline-subsection-title">Dataset Summary</div>', unsafe_allow_html=True)
    _render_dataset_summary_row("Active Vehicle Details", "active_vehicle_details.csv")
    _render_dataset_summary_row("Sold Cars", "sold_cars.csv")
    _render_dataset_summary_row("Referred Cars", "referred_cars.csv")

    active_df = _safe_read_csv(dataset_path("active_vehicle_details.csv"))
    with st.expander("Preview tables", expanded=False):
        if active_df.empty:
            st.info("active_vehicle_details.csv is empty.")
        else:
            sample_cols = [
                col
                for col in [
                    "status",
                    "year",
                    "make",
                    "model",
                    "variant",
                    "price",
                    "bids",
                    "time_remaining_or_date_sold",
                    "url",
                ]
                if col in active_df.columns
            ]
            st.dataframe(active_df[sample_cols].head(50), use_container_width=True, hide_index=True)


def render_stage_7_panel() -> None:
    _render_stage_header(
        "Stage 7",
        "Audit",
        "Check locked schemas and validate the handoff between raw, normalised, and static datasets.",
    )
    if st.button("Run: Audit & Lock", key="panel_stage7_run"):
        _run_stage_command(
            [sys.executable, "scripts/pipeline_stages.py", "audit"],
            spinner_text="Auditing schemas...",
            success_text="Schema audit completed.",
        )
    _render_rules_block(
        "Rules",
        [
            "- Raw, normalised, and static datasets must match exact schema contracts.",
            "- Schema mismatches are surfaced before later stages consume the data.",
            "- This stage is the quality gate for pipeline stability.",
        ],
    )
    st.markdown('<div class="pipeline-subsection-title">Dataset Summary</div>', unsafe_allow_html=True)
    _render_dataset_summary_row("Active Vehicle Details", "active_vehicle_details.csv")
    with st.expander("Audit results", expanded=True):
        _render_schema_audit_block(show_header=False)


STAGE_CONFIG = {
    "Links": {
        "step": "Stage 1",
        "title": "Links",
        "subtitle": "Collect source URLs from Grays.",
        "panel": render_stage_1_panel,
    },
    "Details": {
        "step": "Stage 2",
        "title": "Details",
        "subtitle": "Extract raw vehicle attributes.",
        "panel": render_stage_2_panel,
    },
    "Normalise": {
        "step": "Stage 3",
        "title": "Normalise",
        "subtitle": "Standardise fields and formats.",
        "panel": render_stage_3_panel,
    },
    "Exclude": {
        "step": "Stage 4",
        "title": "Exclude",
        "subtitle": "Remove invalid and out-of-scope rows.",
        "panel": render_stage_4_panel,
    },
    "Canonical": {
        "step": "Stage 5",
        "title": "Canonical",
        "subtitle": "Assign canonical tags and mappings.",
        "panel": render_stage_5_panel,
    },
    "Active": {
        "step": "Stage 6",
        "title": "Active Listings",
        "subtitle": "Refresh live bids and output tables.",
        "panel": render_stage_6_panel,
    },
    "Audit": {
        "step": "Stage 7",
        "title": "Audit",
        "subtitle": "Run schema and handoff checks.",
        "panel": render_stage_7_panel,
    },
}


def _render_pipeline_graph(selected_stage: str) -> None:
    section_html = clean_html(
        """
        <div class="autosniper-section pipeline-block">
            <div class="section-title">Pipeline Flow Chart</div>
            <div class="section-subtitle">Primary system flow from intake to live outputs. The selected stage is highlighted.</div>
        </div>
        """
    )
    st.markdown(section_html, unsafe_allow_html=True)
    nodes = [
        ("Source", "Grays", "Search pages and lot pages."),
        ("Links", "Links", "all_vehicle_links.csv + active queue"),
        ("Details", "Details", "raw_vehicle_data.csv"),
        ("Normalise", "Normalise", "normalised_data.csv"),
        ("Exclude", "Exclude", "excluded_listings.csv + static rows"),
        ("Canonical", "Canonical", "matched / unmatched canonical details"),
        ("Active", "Active Listings", "active, sold, and referred outputs"),
    ]
    parts = ['<div class="pipeline-shell"><div class="pipeline-diagram">']
    for index, (node_key, title, subtitle) in enumerate(nodes):
        selected_class = " is-selected" if node_key == selected_stage else ""
        kicker = STAGE_CONFIG.get(node_key, {}).get("step", "Source")
        parts.append(
            f"""
            <div class="pipeline-node{selected_class}">
                <div class="pipeline-node-step">{kicker}</div>
                <div class="pipeline-node-title">{title}</div>
                <div class="pipeline-node-subtitle">{subtitle}</div>
            </div>
            """
        )
        if index < len(nodes) - 1:
            parts.append('<div class="pipeline-arrow">↓</div>')
    parts.append("</div></div>")
    st.markdown(clean_html("".join(parts)), unsafe_allow_html=True)
    st.caption("The canonical stage feeds live active outputs, which then drive restricted datasets and AI analysis.")


# -----------------------------
# MAIN LAYOUT
# -----------------------------
default_stage = "Links"
stage_options = list(STAGE_CONFIG.keys())
selected_stage = st.session_state.get("pipeline_stage_selector", default_stage)
if selected_stage not in STAGE_CONFIG:
    selected_stage = default_stage
st.markdown("## Pipeline Overview")
_render_pipeline_graph(selected_stage)
if hasattr(st, "segmented_control"):
    stage = st.segmented_control("Stage Selector", stage_options, default=selected_stage, key="pipeline_stage_selector")
else:
    stage = st.radio(
        "Stage Selector",
        stage_options,
        horizontal=True,
        index=stage_options.index(selected_stage),
        key="pipeline_stage_selector",
    )
st.caption("Select one stage to inspect its controls, summaries, rules, logs, and preview tables.")
STAGE_CONFIG[stage]["panel"]()
