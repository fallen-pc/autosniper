from __future__ import annotations

import pandas as pd
import streamlit as st

from shared.comps_engine import parse_currency, parse_numeric
from shared.curves import load_curves, interpolate_base_by_year
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.grouping import GROUP_IDS
from shared.parts_cost import estimate_parts_cost
from shared.repair_features import build_repair_features, serialize_tags
from shared.spec import (
    get_group_spec,
    get_spec_error,
    is_series_allowed,
    load_spec,
    resolve_series_for_year,
    validate_curve_requirements,
)
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro


st.set_page_config(page_title="MISSED OPPORTUNITIES", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "MISSED OPPORTUNITIES",
    "Compare sold results against curve-based estimates for the restricted universe.",
)

required_files = [
    "sold_cars_restricted.csv",
    "restricted_group_map.csv",
    "curves.csv",
]
missing = ensure_datasets_available(required_files)
if missing:
    st.error(
        "Missing required datasets: "
        + ", ".join(missing)
        + ". Run the restricted dataset build and ensure curves.csv exists."
    )
    st.stop()


def _format_currency(value: float | None) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"${value:,.0f}"


def _format_percent(value: float | None) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{value * 100:,.1f}%"


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


@st.cache_data(ttl=300)
def enrich_repair_estimates(df: pd.DataFrame, include_cost: bool) -> pd.DataFrame:
    if df.empty:
        return df
    records = []
    for _, row in df.iterrows():
        features = build_repair_features(row.get("general_condition"))
        if include_cost:
            parts_cost, parts_detail = estimate_parts_cost(features.tags, features.severity)
        else:
            parts_cost, parts_detail = None, None
        records.append(
            {
                "repair_tags": serialize_tags(features.tags),
                "repair_severity": features.severity,
                "repair_decision": features.decision_label,
                "repair_cost_estimate": parts_cost,
                "repair_cost_detail": parts_detail,
            }
        )
    enriched = pd.DataFrame(records, index=df.index)
    return pd.concat([df, enriched], axis=1)


@st.cache_data(ttl=300)
def load_sold_data() -> pd.DataFrame:
    sold_path = dataset_path("sold_cars_restricted.csv")
    df = pd.read_csv(sold_path)
    df["url"] = df["url"].astype(str).str.strip()
    df["odometer_numeric"] = df["odometer_reading"].apply(parse_numeric)
    df["price_numeric"] = df["price"].apply(parse_currency)
    return df


@st.cache_data(ttl=300)
def load_group_map() -> pd.DataFrame:
    path = dataset_path("restricted_group_map.csv")
    df = pd.read_csv(path)
    df["url"] = df["url"].astype(str).str.strip()
    return df


curves_df = load_curves()
sold_df = load_sold_data()
group_map_df = load_group_map()
spec = load_spec()
spec_error = get_spec_error(spec)
if spec_error == "pyyaml_missing":
    st.warning("Spec checks disabled: install `pyyaml` to enable config/spec_v1.yaml validation.")
    spec = {}

spec_issues = validate_curve_requirements(spec, curves_df) if spec else []
if spec_issues:
    issue_preview = "\n".join(spec_issues[:10])
    extra = "" if len(spec_issues) <= 10 else f"\n...and {len(spec_issues) - 10} more"
    st.warning(f"Spec/curve issues detected:\n{issue_preview}{extra}")

sold_groups = group_map_df[group_map_df["source"] == "sold"][["url", "group_id"]].drop_duplicates(
    "url"
)
sold_df = sold_df.merge(sold_groups, on="url", how="left")
sold_df = sold_df.dropna(subset=["group_id", "price_numeric"]).copy()

st.sidebar.header("Filters")
group_filter = st.sidebar.selectbox("Group ID", ["All"] + sorted(GROUP_IDS))
only_misses = st.sidebar.checkbox("Only show sold below curve estimate", value=True)
min_delta = st.sidebar.number_input("Minimum delta ($)", min_value=0, value=0, step=100)
include_repairs = st.sidebar.checkbox("Estimate repairs from condition notes", value=True)
only_net_positive = False
if include_repairs:
    only_net_positive = st.sidebar.checkbox("Only show net positive after repairs", value=False)

if "general_condition" not in sold_df.columns:
    if include_repairs:
        include_repairs = False
    st.warning(
        "general_condition missing: repair estimates and engine defect exclusions are disabled."
    )
else:
    sold_df = enrich_repair_estimates(sold_df, include_cost=include_repairs)
    major_mask = sold_df["repair_tags"].fillna("").str.contains(
        "engine_mechanical|non_operational", case=False, na=False
    )
    excluded_count = int(major_mask.sum())
    if excluded_count:
        st.info(f"Excluded {excluded_count:,} listings with major engine defects.")
    sold_df = sold_df[~major_mask].copy()

results: list[dict[str, object]] = []
for _, row in sold_df.iterrows():
    group_id = row.get("group_id")
    year_val = _safe_int(row.get("year"))
    odo_val = row.get("odometer_numeric")
    spec_reason = ""
    series_key = None
    spec_group = get_group_spec(spec, group_id) if spec else None
    if spec and not spec_group:
        spec_reason = "UNKNOWN_GROUP_MAPPING"
    elif spec_group:
        series_key, spec_reason = resolve_series_for_year(spec, group_id, year_val)
        if not spec_reason and series_key and not is_series_allowed(spec_group, series_key):
            spec_reason = "SERIES_NOT_COVERED"

    curve_subset = curves_df
    if group_id:
        curve_subset = curve_subset[curve_subset["group_id"] == group_id]
    if series_key and not curve_subset.empty:
        curve_subset = curve_subset[curve_subset["series"] == series_key]
        if curve_subset.empty and not spec_reason:
            spec_reason = "SERIES_NOT_COVERED"

    curve_estimate = None
    if not spec_reason:
        curve_estimate = interpolate_base_by_year(curve_subset, group_id, year_val, odo_val)
    if curve_estimate is None and not spec_reason:
        spec_reason = "NOT_COVERED"

    sold_price = row.get("price_numeric")
    repair_cost = row.get("repair_cost_estimate") if include_repairs else None
    delta = None
    delta_pct = None
    if curve_estimate is not None and sold_price is not None:
        delta = curve_estimate - sold_price
        if curve_estimate > 0:
            delta_pct = delta / curve_estimate
    net_delta = None
    if delta is not None:
        net_delta = delta - (repair_cost or 0)

    results.append(
        {
            "url": row.get("url"),
            "year": row.get("year"),
            "make": row.get("make"),
            "model": row.get("model"),
            "variant": row.get("variant"),
            "odometer_reading": row.get("odometer_reading"),
            "price": row.get("price"),
            "group_id": group_id,
            "spec_series": series_key,
            "spec_reason": spec_reason,
            "curve_estimate": curve_estimate,
            "delta": delta,
            "delta_pct": delta_pct,
            "repair_cost_estimate": repair_cost,
            "repair_severity": row.get("repair_severity") if include_repairs else None,
            "repair_decision": row.get("repair_decision") if include_repairs else None,
            "net_delta": net_delta,
        }
    )

results_df = pd.DataFrame(results)

if group_filter != "All":
    results_df = results_df[results_df["group_id"] == group_filter]
if only_misses:
    results_df = results_df[results_df["delta"].fillna(0) > 0]
if min_delta > 0:
    results_df = results_df[results_df["delta"].fillna(0) >= min_delta]
if only_net_positive:
    results_df = results_df[results_df["net_delta"].fillna(0) > 0]

results_df = results_df.sort_values("delta", ascending=False)

total_count = len(results_df)
with_estimate = results_df["curve_estimate"].notna().sum()
positive_delta = results_df["delta"].fillna(0).gt(0).sum()
avg_delta = results_df.loc[results_df["delta"].notna(), "delta"].mean()
avg_net_delta = results_df.loc[results_df["net_delta"].notna(), "net_delta"].mean()

metrics_cols = st.columns(4)
metrics_cols[0].metric("Sold Listings", f"{total_count:,}")
metrics_cols[1].metric("With Curve Estimate", f"{with_estimate:,}")
metrics_cols[2].metric("Potential Misses", f"{positive_delta:,}")
metrics_cols[3].metric(
    "Avg Delta (After Repairs)" if include_repairs else "Average Delta",
    _format_currency(avg_net_delta) if include_repairs else _format_currency(avg_delta),
)

st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Restricted Sold (Missed Opportunities)</div>
            <div class="section-subtitle">
                <strong>curve_estimate</strong>: curve-based resale estimate from year + km.<br/>
                <strong>delta</strong>: curve_estimate minus sold price (positive means sold below curve).<br/>
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

display_df = results_df.copy()
display_df["curve_estimate"] = display_df["curve_estimate"].apply(_format_currency)
display_df["delta"] = display_df["delta"].apply(_format_currency)
display_df["delta_pct"] = display_df["delta_pct"].apply(_format_percent)
if include_repairs:
    display_df["repair_cost_estimate"] = display_df["repair_cost_estimate"].apply(_format_currency)
    display_df["net_delta"] = display_df["net_delta"].apply(_format_currency)

display_columns = [
    "year",
    "make",
    "model",
    "variant",
    "odometer_reading",
    "price",
    "group_id",
    "spec_series",
    "spec_reason",
    "curve_estimate",
    "delta",
    "delta_pct",
    "repair_cost_estimate",
    "repair_severity",
    "repair_decision",
    "net_delta",
    "url",
]
available_columns = [col for col in display_columns if col in display_df.columns]
st.dataframe(display_df[available_columns], width="stretch")
