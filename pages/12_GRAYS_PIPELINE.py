import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path
from shared.schema import ACTIVE_LISTING_SCHEMA, SOLD_RAW_SCRAPE_COLUMNS, STATIC_VEHICLE_SCHEMA
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro
from shared.validators import R
from shared.sold_cleaning import COMPLIANCE_SLUG_PATTERN

try:
    from scripts.extract_vehicle_details import WOVR_PATTERN
except Exception:  # noqa: BLE001
    WOVR_PATTERN = None


st.set_page_config(page_title="GRAYS PIPELINE", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "GRAYS PIPELINE",
    "End-to-end visibility from link extraction to active vehicle details.",
    show_logo=False,
)

STATIC_OUTPUT_SCHEMA = list(
    dict.fromkeys(list(STATIC_VEHICLE_SCHEMA) + ["canonical_tag", "canonical_reason"])
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


def _file_summary(path: Path) -> dict[str, str]:
    if not path.exists():
        return {
            "status": "Missing",
            "rows": "0",
            "columns": "0",
            "modified": "—",
        }
    df = _safe_read_csv(path)
    modified = _format_ts(path.stat().st_mtime)
    return {
        "status": "Present",
        "rows": f"{len(df):,}",
        "columns": f"{df.shape[1]:,}",
        "modified": modified,
    }


def _render_dataset_block(
    title: str,
    filename: str,
    *,
    schema: Optional[Iterable[str]] = None,
    sample_rows: int = 20,
    key_prefix: str,
) -> None:
    path = dataset_path(filename)
    summary = _file_summary(path)
    section_html = clean_html(
        f"""
        <div class="autosniper-section pipeline-stage">
            <div class="section-title">{title}</div>
            <div class="section-subtitle">{filename}</div>
        </div>
        """
    )
    st.markdown(section_html, unsafe_allow_html=True)
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Status", summary["status"])
    col_b.metric("Rows", summary["rows"])
    col_c.metric("Columns", summary["columns"])
    col_d.metric("Last modified", summary["modified"])

    button_cols = st.columns(4)
    show_schema = button_cols[0].button("Show schema", key=f"{key_prefix}_schema")
    show_columns = button_cols[1].button("Show columns", key=f"{key_prefix}_columns")
    show_sample = button_cols[2].button("Show sample", key=f"{key_prefix}_sample")
    show_preview = button_cols[3].button("Preview 100", key=f"{key_prefix}_preview")

    if show_schema:
        if schema:
            with st.expander("Schema", expanded=True):
                st.dataframe(_schema_table(schema), use_container_width=True, hide_index=True)
        else:
            st.info("No schema declared for this dataset.")
    if show_columns:
        if path.exists():
            df = _safe_read_csv(path)
            with st.expander("Columns", expanded=True):
                st.dataframe(_schema_table(df.columns), use_container_width=True, hide_index=True)
        else:
            st.info("File missing.")
    if show_sample:
        if path.exists():
            df = _safe_read_csv(path)
            with st.expander("Sample rows", expanded=True):
                st.dataframe(df.head(sample_rows), use_container_width=True, hide_index=True)
        else:
            st.info("File missing.")
    if show_preview:
        if path.exists():
            df = _safe_read_csv(path)
            with st.expander("Preview rows", expanded=True):
                st.dataframe(df.head(100), use_container_width=True, hide_index=True)
        else:
            st.info("File missing.")


def _render_rules_block() -> None:
    section_html = clean_html(
        """
        <div class="autosniper-section pipeline-block">
            <div class="section-title">Rules & Exclusions</div>
            <div class="section-subtitle">Validation logic and filters applied in the Grays pipeline.</div>
        </div>
        """
    )
    st.markdown(section_html, unsafe_allow_html=True)
    rule_cols = st.columns(4)
    show_reasons = rule_cols[0].button("Show reason codes", key="rules_reasons")
    show_normalise = rule_cols[1].button("Normalise rules", key="rules_normalise")
    show_exclusions = rule_cols[2].button("Exclusion rules", key="rules_exclusions")
    show_compliance = rule_cols[3].button("Compliance/WOVR", key="rules_compliance")

    if show_reasons:
        reason_items = []
        for name, value in vars(R).items():
            if name.startswith("_"):
                continue
            if not isinstance(value, str):
                continue
            reason_items.append({"code": value, "label": name.replace("_", " ").title()})
        st.dataframe(pd.DataFrame(sorted(reason_items, key=lambda r: r["code"])), use_container_width=True)

    if show_normalise:
        with st.expander("Normalise rules (applied to raw → normalised)", expanded=True):
            st.markdown(
                "\n".join(
                    [
                        "- Remove compliance slugs and compliance notes from URLs and condition text.",
                        "- Normalize make/model casing and strip compliance markers.",
                        "- Normalize fuel type (petrol/diesel/hybrid/electric mapping).",
                        "- Normalize transmission (auto/manual/CVT).",
                        "- Clean odometer and engine capacity formats.",
                        "- Normalize rego expiry + fallback to Unregistered.",
                        "- Remove transmission/fuel/seat/cert notes from variant.",
                        "- Apply body type alias rules based on variant text.",
                    ]
                )
            )
            st.caption("Source: shared/sold_cleaning.py → normalize_listing_fields")

    if show_exclusions:
        with st.expander("Exclusion rules (applied to normalised → static)", expanded=True):
            st.markdown(
                "\n".join(
                    [
                        "- Drop missing/invalid URL or non-HTTP URL.",
                        "- Drop non-vehicle listings (motorcycles, trailers, boats).",
                        "- Drop missing or out-of-range year.",
                        "- Drop missing make/model/body/fuel/transmission/location.",
                        "- Drop missing/invalid odometer (range + suspect checks).",
                        "- Drop bad VIN when present.",
                        "- Enforce allowed body types list.",
                    ]
                )
            )
            st.caption("Source: shared/validators.py → validate_static_row")

    if show_compliance:
        st.code(f"COMPLIANCE_SLUG_PATTERN = {COMPLIANCE_SLUG_PATTERN.pattern}", language="text")
        if WOVR_PATTERN is None:
            st.info("WOVR pattern not available.")
        else:
            st.code(f"WOVR_PATTERN = {WOVR_PATTERN.pattern}", language="text")
        st.write("Non-vehicle filters: MOTORCYCLE, TRAILER, BOAT (shared/validators.py).")


def _render_exclusions_block() -> None:
    excluded_path = dataset_path("excluded_listings.csv")
    sold_path = dataset_path("sold_cars.csv")
    referred_path = dataset_path("referred_cars.csv")
    section_html = clean_html(
        """
        <div class="autosniper-section pipeline-block">
            <div class="section-title">Excluded Listings</div>
            <div class="section-subtitle">Rows dropped during static validation.</div>
        </div>
        """
    )
    st.markdown(section_html, unsafe_allow_html=True)
    if not excluded_path.exists():
        st.info("excluded_listings.csv is missing.")
        return
    excluded_df = _safe_read_csv(excluded_path)
    if not excluded_df.empty:
        excluded_df = excluded_df.reset_index(drop=True)
        excluded_df.insert(0, "row_id", excluded_df.index + 1)
    sold_df = _safe_read_csv(sold_path) if sold_path.exists() else pd.DataFrame()
    referred_df = _safe_read_csv(referred_path) if referred_path.exists() else pd.DataFrame()
    sold_urls = set(
        sold_df.get("url", pd.Series(dtype=str))
        .dropna()
        .astype(str)
        .str.strip()
        .tolist()
    )
    referred_urls = set(
        referred_df.get("url", pd.Series(dtype=str))
        .dropna()
        .astype(str)
        .str.strip()
        .tolist()
    )
    current_mask = ~excluded_df.get("url", pd.Series(dtype=str)).isin(sold_urls | referred_urls)
    current_exclusions = excluded_df[current_mask].copy() if not excluded_df.empty else excluded_df

    excluded_run_count = 0
    if not excluded_df.empty and "timestamp" in excluded_df.columns:
        ts_series = pd.to_datetime(excluded_df["timestamp"], errors="coerce")
        latest_ts = ts_series.max()
        if pd.notna(latest_ts):
            excluded_run_count = int((ts_series == latest_ts).sum())
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Total excluded", f"{len(excluded_df):,}")
    with col_b:
        st.metric("Current exclusions", f"{len(current_exclusions):,}")
    with col_c:
        st.metric("Excluded this run", f"{excluded_run_count:,}")

    button_cols = st.columns(5)
    show_current = button_cols[0].button("Current exclusions", key="excluded_current")
    show_total = button_cols[1].button("Total exclusions", key="excluded_total")
    show_counts = button_cols[2].button("Reason counts", key="excluded_counts")
    show_latest = button_cols[3].button("Latest 50 rows", key="excluded_latest")
    show_columns = button_cols[4].button("Show columns", key="excluded_cols")

    if show_current:
        with st.expander("Current exclusions (not sold/referred)", expanded=True):
            st.dataframe(current_exclusions.tail(200), use_container_width=True, hide_index=True)
    if show_total:
        with st.expander("Total exclusions", expanded=True):
            st.dataframe(excluded_df.tail(200), use_container_width=True, hide_index=True)
    if show_counts and "reason_code" in excluded_df.columns:
        counts = current_exclusions["reason_code"].value_counts().reset_index()
        counts.columns = ["reason_code", "count"]
        with st.expander("Current exclusion reason counts", expanded=True):
            st.dataframe(counts, use_container_width=True, hide_index=True)
    if show_latest:
        with st.expander("Latest exclusions", expanded=True):
            st.dataframe(excluded_df.tail(50), use_container_width=True, hide_index=True)
    if show_columns:
        with st.expander("Excluded columns", expanded=True):
            st.dataframe(_schema_table(excluded_df.columns), use_container_width=True, hide_index=True)


def _render_stage_controls() -> None:
    stage_html = clean_html(
        """
        <div class="autosniper-section pipeline-block">
            <div class="section-title">Pipeline Controls</div>
            <div class="section-subtitle">Run each stage directly from here.</div>
        </div>
        """
    )
    st.markdown(stage_html, unsafe_allow_html=True)

    col_a, col_b, col_c = st.columns(3)
    run_links = col_a.button("Run link scraper", key="pipeline_run_links")
    run_details = col_b.button("Run detail scraper", key="pipeline_run_details")
    run_details_batch = col_c.number_input(
        "Detail batch size (0 = full run)",
        min_value=0,
        max_value=500,
        value=0,
        step=1,
        key="pipeline_detail_batch",
    )

    if run_links:
        with st.spinner("Running link scraper..."):
            exit_code = os.system("python scripts/extract_links.py")
            if exit_code == 0:
                st.success("Link scraper completed.")
            else:
                st.error("Link scraper failed. Check terminal output.")

    if run_details:
        with st.spinner("Running detail scraper..."):
            command = "python scripts/extract_vehicle_details.py"
            if run_details_batch > 0:
                command += f" --batch-size {int(run_details_batch)}"
            exit_code = os.system(command)
            if exit_code == 0:
                st.success("Detail scraper completed.")
            else:
                st.error("Detail scraper failed. Check terminal output.")


_render_stage_controls()

count_files = [
    "all_vehicle_links.csv",
    "active_vehicle_links.csv",
    "raw_vehicle_data.csv",
    "normalised_data.csv",
    "vehicle_static_details.csv",
    "active_vehicle_details.csv",
]
count_rows = []
for name in count_files:
    path = dataset_path(name)
    if path.exists():
        df = _safe_read_csv(path)
        count_rows.append({"dataset": name, "rows": len(df)})
    else:
        count_rows.append({"dataset": name, "rows": 0})
if count_rows:
    counts_df = pd.DataFrame(count_rows)
    st.markdown(
        clean_html(
            """
            <div class="autosniper-section pipeline-block">
                <div class="section-title">Pipeline Counts</div>
                <div class="section-subtitle">Row counts for each core CSV.</div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )
    st.dataframe(counts_df, use_container_width=True, hide_index=True)

flow_html = clean_html(
    """
    <div class="autosniper-section pipeline-block">
        <div class="section-title">Current Pipeline Flow</div>
        <div class="section-subtitle">
            Raw and normalised snapshots are written before exclusions. Static is written after exclusions + tagging.
        </div>
        <div style="margin-top:0.6rem;">
            <div class="autosniper-chip">1. extract_links → all_vehicle_links.csv</div>
            <div class="autosniper-chip">1b. active_links → active_vehicle_links.csv</div>
            <div class="autosniper-chip">2. scrape_links → raw_vehicle_data.csv</div>
            <div class="autosniper-chip">3. normalise_rules → normalised_data.csv</div>
            <div class="autosniper-chip">4. exclusion_rules → excluded_listings.csv</div>
            <div class="autosniper-chip">5. static_export + tagging → vehicle_static_details.csv</div>
            <div class="autosniper-chip">6. seed active → active_vehicle_details.csv</div>
        </div>
        <div style="margin-top:0.6rem;color:rgba(255,255,255,0.7);font-size:0.85rem;">
            Raw/normalised omit canonical_tag + canonical_reason by design.
        </div>
    </div>
    """
)
st.markdown(flow_html, unsafe_allow_html=True)

with st.expander("Flow chart", expanded=True):
    st.markdown(
        """
```mermaid
flowchart TD
    A[collect_links] --> B[all_vehicle_links.csv]
    A --> B2[active_vehicle_links.csv]
    B --> C[scrape_links]
    C --> D[raw_vehicle_data.csv]
    D --> E[normalise_rules]
    E --> F[normalised_data.csv]
    F --> G{exclusion_rules}
    G -- excluded --> H[excluded_listings.csv]
    G -- kept --> I[static_export + tagging]
    I --> J[vehicle_static_details.csv]
    J --> K[seed_active]
    K --> L[active_vehicle_details.csv]
```
        """
    )

_render_dataset_block(
    "Stage 1: Link Extraction",
    "all_vehicle_links.csv",
    schema=["url", "discovered_at"],
    key_prefix="links",
)

_render_dataset_block(
    "Stage 1b: Active Link Queue",
    "active_vehicle_links.csv",
    schema=["url"],
    key_prefix="active_links",
)

_render_dataset_block(
    "Stage 2: Raw Vehicle Data",
    "raw_vehicle_data.csv",
    schema=SOLD_RAW_SCRAPE_COLUMNS,
    key_prefix="raw",
)

_render_dataset_block(
    "Stage 3: Normalised Vehicle Data",
    "normalised_data.csv",
    schema=SOLD_RAW_SCRAPE_COLUMNS,
    key_prefix="norm",
)

_render_exclusions_block()
_render_rules_block()

_render_dataset_block(
    "Stage 4: Static Vehicle Details",
    "vehicle_static_details.csv",
    schema=STATIC_OUTPUT_SCHEMA,
    key_prefix="static",
)

_render_dataset_block(
    "Stage 5: Active Vehicle Details",
    "active_vehicle_details.csv",
    schema=ACTIVE_LISTING_SCHEMA,
    key_prefix="active",
)
