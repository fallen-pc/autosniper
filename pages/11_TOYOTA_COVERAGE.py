from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from shared.canonical_tagging import is_canonical_eligible
from shared.csv_utils import read_csv_stable
from shared.curves import list_curve_tags, load_curves
from shared.data_loader import dataset_path
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro


st.set_page_config(page_title="Toyota Coverage", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "TOYOTA COVERAGE",
    "Compare canonical tag coverage across platforms (Grays, Autotrader, Carsales).",
    show_logo=False,
)


def _load_source(path: Path, source_label: str) -> pd.DataFrame:
    if not path.exists():
        st.warning(f"Missing source file: {path}")
        return pd.DataFrame()
    try:
        df = read_csv_stable(path)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not read {path}: {exc}")
        return pd.DataFrame()
    if "canonical_tag" not in df.columns:
        st.warning(f"{path} has no canonical_tag column. Skipping {source_label}.")
        return pd.DataFrame()
    df = df.copy()
    canonical = df["canonical_tag"].fillna("").astype(str).str.strip()
    canonical = canonical.mask(canonical.str.lower().isin(["nan", "none"]), "")
    df["canonical_tag"] = canonical
    df["source"] = source_label
    if "canonical_reason" not in df.columns:
        df["canonical_reason"] = ""
    if "make" not in df.columns:
        df["make"] = df["canonical_tag"].astype(str).str.split("_").str[0]
    return df


def _toyota_filter(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    make_series = df["make"].astype(str).str.lower().str.strip()
    tag_series = df["canonical_tag"].astype(str).str.lower().str.strip()
    return df[(make_series == "toyota") | tag_series.str.startswith("toyota_")].copy()


def _build_summary(
    df: pd.DataFrame, split_eligibility: bool
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    df["canonical_tag"] = df["canonical_tag"].astype(str).str.strip()
    df = df[df["canonical_tag"] != ""].copy()
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    if split_eligibility:
        df["eligible"] = df.apply(
            lambda row: is_canonical_eligible(
                row.get("canonical_tag"), row.get("canonical_reason")
            ),
            axis=1,
        )
        summary = (
            df.groupby(["canonical_tag", "source", "eligible"])
            .size()
            .reset_index(name="count")
        )
        pivot = summary.pivot_table(
            index="canonical_tag",
            columns=["source", "eligible"],
            values="count",
            fill_value=0,
        )
        pivot.columns = [
            f"{source}_{'eligible' if eligible else 'ineligible'}"
            for source, eligible in pivot.columns
        ]
    else:
        summary = (
            df.groupby(["canonical_tag", "source"])
            .size()
            .reset_index(name="count")
        )
        pivot = summary.pivot(
            index="canonical_tag",
            columns="source",
            values="count",
        ).fillna(0)
    pivot = pivot.astype(int)
    pivot["total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values(by="total", ascending=False)
    return summary.sort_values(["canonical_tag", "source"]), pivot


def _build_policy_audit(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "source" not in df.columns:
        return pd.DataFrame()
    working = df.copy()
    working["canonical_reason"] = (
        working.get("canonical_reason", "")
        .fillna("")
        .astype(str)
        .str.strip()
    )
    working["eligible"] = working.apply(
        lambda row: is_canonical_eligible(
            row.get("canonical_tag"), row.get("canonical_reason")
        ),
        axis=1,
    )
    summary = (
        working.groupby("source")
        .agg(
            total=("canonical_tag", "size"),
            eligible=("eligible", "sum"),
        )
        .reset_index()
    )
    summary["ineligible"] = summary["total"] - summary["eligible"]
    return summary


st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Coverage inputs</div>
            <div class="section-subtitle">
                Choose which tagged sources to include. This report never alters pipeline data.
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

include_grays_active = st.checkbox("Include Grays active", value=True)
include_grays_sold = st.checkbox("Include Grays sold", value=False)
include_autotrader = st.checkbox("Include Autotrader snapshot", value=True)

toyota_only = st.checkbox("Toyota only", value=True)
split_eligibility = st.checkbox("Split eligible vs ineligible", value=False)

sources: list[pd.DataFrame] = []
if include_grays_active:
    sources.append(_load_source(dataset_path("active_vehicle_details.csv"), "grays"))
if include_grays_sold:
    sources.append(_load_source(dataset_path("sold_cars.csv"), "grays"))
if include_autotrader:
    sources.append(_load_source(Path("autotrader_isolated/output/first_page_results.csv"), "autotrader"))

if sources:
    combined = pd.concat(sources, ignore_index=True, sort=False)
else:
    combined = pd.DataFrame()

if toyota_only:
    combined = _toyota_filter(combined)

curves_df = load_curves()
if curves_df.empty:
    st.warning("curves.csv is empty; showing all tags.")
else:
    allowed_tags = list_curve_tags(curves_df)
    if not allowed_tags:
        st.warning("No canonical tags found in curves.csv; showing all tags.")
    else:
        combined = combined[
            combined["canonical_tag"].astype(str).str.strip().isin(allowed_tags)
        ].copy()

summary_df, pivot_df = _build_summary(combined, split_eligibility=split_eligibility)
audit_df = _build_policy_audit(combined)

if combined.empty:
    st.info("No data available for the selected sources.")
else:
    st.markdown(
        clean_html(
            """
            <div class="autosniper-section">
                <div class="section-title">Coverage summary</div>
                <div class="section-subtitle">Counts per canonical tag and platform.</div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )
    st.dataframe(
        pivot_df.reset_index(),
        width="stretch",
        hide_index=True,
    )
    st.markdown("**Long form (canonical_tag | source | count)**")
    st.dataframe(summary_df, width="stretch", hide_index=True)

    if not audit_df.empty:
        st.markdown("**Policy audit (eligibility)**")
        st.dataframe(
            audit_df,
            width="stretch",
            hide_index=True,
        )

    export_path = Path("CSV_data/reports/toyota_tag_counts_by_platform.csv")
    if st.button("Export summary CSV"):
        export_path.parent.mkdir(parents=True, exist_ok=True)
        summary_df.to_csv(export_path, index=False)
        st.success(f"Saved {export_path}")
