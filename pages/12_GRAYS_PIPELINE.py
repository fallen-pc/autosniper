import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path
from shared.schema import STATIC_VEHICLE_SCHEMA
from shared.curves import load_curves
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
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


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
    st.markdown("## Stage 1 - Scrape Links")
    if st.button("Run: Scrape Links", key="panel_stage1_run"):
        _run_stage_command(
            [sys.executable, "scripts/extract_links.py"],
            spinner_text="Running link scraper...",
            success_text="Link scraping completed.",
        )
    _render_dataset_summary_row("All Vehicle Links", "all_vehicle_links.csv")
    _render_dataset_summary_row("Active Link Queue", "active_vehicle_links.csv")
    with st.expander("Preview data", expanded=False):
        for fname in ["all_vehicle_links.csv", "active_vehicle_links.csv"]:
            st.markdown(f"### {fname}")
            path = dataset_path(fname)
            if path.exists():
                st.dataframe(_safe_read_csv(path).head(50), use_container_width=True, hide_index=True)
            else:
                st.info("Missing.")


def render_stage_2_panel() -> None:
    st.markdown("## Stage 2 - Scrape Details")
    if st.button("Run: Scrape Details", key="panel_stage2_run"):
        _run_stage_command(
            [sys.executable, "scripts/extract_vehicle_details.py", "--raw-only"],
            spinner_text="Running detail scrape...",
            success_text="Detail scraping completed.",
        )
    _render_dataset_summary_row("Raw Vehicle Data", "raw_vehicle_data.csv")
    with st.expander("Schema + Sample", expanded=False):
        st.dataframe(_schema_table(STATIC_VEHICLE_SCHEMA), use_container_width=True, hide_index=True)
        st.dataframe(
            _safe_read_csv(dataset_path("raw_vehicle_data.csv")).head(50),
            use_container_width=True,
            hide_index=True,
        )


def render_stage_3_panel() -> None:
    st.markdown("## Stage 3 - Normalise")
    if st.button("Run: Normalise", key="panel_stage3_run"):
        _run_stage_command(
            [sys.executable, "scripts/pipeline_stages.py", "normalize"],
            spinner_text="Running normalisation stage...",
            success_text="Normalisation completed.",
        )
    _render_dataset_summary_row("Normalised Data", "normalised_data.csv")
    with st.expander("Rules + Sample", expanded=False):
        st.markdown("\n".join(_normalise_rule_lines()))
        st.dataframe(
            _safe_read_csv(dataset_path("normalised_data.csv")).head(50),
            use_container_width=True,
            hide_index=True,
        )


def render_stage_4_panel() -> None:
    st.markdown("## Stage 4 - Apply Exclusions")
    if st.button("Run: Exclusions", key="panel_stage4_run"):
        _run_stage_command(
            [sys.executable, "scripts/pipeline_stages.py", "exclude"],
            spinner_text="Applying exclusion rules...",
            success_text="Exclusion stage completed.",
        )
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

    with st.expander("Exclusion Rules + Table", expanded=False):
        st.markdown("\n".join(_exclusion_rule_lines()))
        if excluded_df.empty:
            st.info("excluded_listings.csv is empty.")
        else:
            table_df = excluded_df.copy().reset_index(drop=True)
            table_df.insert(0, "row_id", table_df.index + 1)
            st.dataframe(table_df.tail(200), use_container_width=True, hide_index=True)


def render_stage_5_panel() -> None:
    st.markdown("## Stage 5 - Canonical Match")
    if st.button("Run: Match Canonical Tags", key="panel_stage5_run"):
        _run_stage_command(
            [sys.executable, "scripts/pipeline_stages.py", "match"],
            spinner_text="Running canonical match...",
            success_text="Canonical match completed.",
        )
    _render_dataset_summary_row("Matched Canonical", "matched_canonical_details.csv")
    _render_dataset_summary_row("Unmatched Canonical", "unmatched_canonical_details.csv")

    curves_df = load_curves()
    available_tags = (
        curves_df["canonical_tag"].dropna().astype(str).str.strip().tolist()
        if not curves_df.empty and "canonical_tag" in curves_df.columns
        else []
    )
    available_tags = sorted({tag for tag in available_tags if tag})
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
    st.markdown("## Stage 6 - Schema Audit")
    if st.button("Run: Audit & Lock", key="panel_stage6_run"):
        _run_stage_command(
            [sys.executable, "scripts/pipeline_stages.py", "audit"],
            spinner_text="Auditing schemas...",
            success_text="Schema audit completed.",
        )
    _render_dataset_summary_row("Active Vehicle Details", "active_vehicle_details.csv")
    with st.expander("Schema Audit Results", expanded=True):
        _render_schema_audit_block(show_header=False)


def _render_pipeline_graph() -> None:
    section_html = clean_html(
        """
        <div class="autosniper-section pipeline-block">
            <div class="section-title">Pipeline Flow Chart</div>
            <div class="section-subtitle">Clear stage-to-stage flow from links to active listings.</div>
        </div>
        """
    )
    st.markdown(section_html, unsafe_allow_html=True)
    dot = """
digraph grays_pipeline {
  rankdir=TB;
  graph [bgcolor="transparent", ranksep="1.0", nodesep="0.6"];
  node [shape=box, style="rounded,filled", fillcolor="#0f1622", color="#2f8fd8", fontcolor="#e6edf6", fontsize=10];
  edge [color="#6a7d92", arrowsize=0.8];

  n1 [label="1. SCRAPE LINKS\\nall_vehicle_links.csv"];
  n2 [label="1b. ACTIVE LINKS\\nactive_vehicle_links.csv"];
  n3 [label="2. SCRAPE DETAILS\\nraw_vehicle_data.csv"];
  n4 [label="3. NORMALISE\\nnormalised_data.csv"];
  n5 [label="4. EXCLUSION LOG\\nexcluded_listings.csv"];
  n6 [label="4b. STATIC DETAILS\\nvehicle_static_details.csv"];
  n7 [label="5. CANONICAL SPLIT\\nmatched/unmatched csv"];
  n8 [label="6. ACTIVE DETAILS\\nactive_vehicle_details.csv"];

  n1 -> n2 -> n3 -> n4 -> n6 -> n7 -> n8;
  n4 -> n5;
}
"""
    st.graphviz_chart(dot, use_container_width=True)
    st.caption("Excluded listings branch from normalised data and do not continue to static/active.")


# -----------------------------
# MAIN LAYOUT
# -----------------------------
st.markdown("## Pipeline Overview")
_render_pipeline_graph()

stage_options = [
    "1 Scrape Links",
    "2 Scrape Details",
    "3 Normalise",
    "4 Exclusions",
    "5 Canonical",
    "6 Audit",
]
if hasattr(st, "segmented_control"):
    stage = st.segmented_control("Open Stage", stage_options, default="1 Scrape Links")
else:
    stage = st.radio("Open Stage", stage_options, horizontal=True, index=0)

if stage == "1 Scrape Links":
    render_stage_1_panel()
elif stage == "2 Scrape Details":
    render_stage_2_panel()
elif stage == "3 Normalise":
    render_stage_3_panel()
elif stage == "4 Exclusions":
    render_stage_4_panel()
elif stage == "5 Canonical":
    render_stage_5_panel()
elif stage == "6 Audit":
    render_stage_6_panel()
