from __future__ import annotations

import time
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from scripts.ai_listing_valuation import run_curve_listing_analysis
from scripts.ai_price_analysis import _extract_hours_remaining
from shared.comps_engine import parse_currency, parse_numeric
from shared.curves import load_curves, interpolate_base_by_year
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.filter_controls import describe_time_selection, render_time_filter
from shared.grouping import GROUP_IDS
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro


st.set_page_config(page_title="AI Pricing Analysis", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "AI PRICING ANALYSIS",
    "Curve-based pricing for the restricted VIC Top-12 universe.",
)


required_files = [
    "active_vehicle_details_restricted.csv",
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


def _format_currency(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"${value:,.0f}"


def _safe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


@st.cache_data(ttl=300)
def load_active_data() -> pd.DataFrame:
    active_path = dataset_path("active_vehicle_details_restricted.csv")
    df = pd.read_csv(active_path)
    df["url"] = df["url"].astype(str).str.strip()
    df["odometer_numeric"] = df["odometer_reading"].apply(parse_numeric)
    df["price_numeric"] = df["price"].apply(parse_currency) if "price" in df.columns else None
    if "time_remaining_or_date_sold" in df.columns:
        df["hours_remaining"] = df["time_remaining_or_date_sold"].apply(_extract_hours_remaining)
    elif "date_sold" in df.columns:
        df["hours_remaining"] = df["date_sold"].apply(_extract_hours_remaining)
    else:
        df["hours_remaining"] = None
    return df


@st.cache_data(ttl=300)
def load_group_map() -> pd.DataFrame:
    path = dataset_path("restricted_group_map.csv")
    df = pd.read_csv(path)
    df["url"] = df["url"].astype(str).str.strip()
    return df


@st.cache_data(ttl=300)
def load_sold_data() -> pd.DataFrame:
    sold_path = dataset_path("sold_cars_restricted.csv")
    df = pd.read_csv(sold_path)
    df["url"] = df["url"].astype(str).str.strip()
    df["price_numeric"] = df["price"].apply(parse_currency)
    return df


curves_df = load_curves()
active_df = load_active_data()
group_map_df = load_group_map()
sold_df = load_sold_data()

active_groups = group_map_df[group_map_df["source"] == "active"][["url", "group_id"]]
active_df = active_df.merge(active_groups, on="url", how="left")

sold_groups = group_map_df[group_map_df["source"] == "sold"][["url", "group_id"]]
sold_df = sold_df.merge(sold_groups, on="url", how="left")

sold_stats = (
    sold_df.dropna(subset=["group_id", "price_numeric"])
    .groupby("group_id")["price_numeric"]
    .agg(["count", "median"])
    .rename(columns={"count": "comps_count", "median": "comps_median"})
)


st.sidebar.header("Filters")
time_label, time_bounds = render_time_filter(
    container=st.sidebar,
    label="Show listings finishing within",
    default_option="< 24h",
)
lower_bound, upper_bound = time_bounds
min_hours = 0.0 if lower_bound is None else lower_bound
max_hours = upper_bound

group_filter = st.sidebar.selectbox("Group ID", ["All"] + sorted(GROUP_IDS))
refresh_clicked = st.sidebar.button("Refresh curve valuations")

time_window_text = describe_time_selection(time_label)
st.caption(f"Restricted active listings finishing within {time_window_text}.")

st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Legend</div>
            <div class="section-subtitle">
                <strong>curve_base</strong>: direct curve estimate from year + km.<br/>
                <strong>comps_median</strong>/<strong>comps_count</strong>: median and count from restricted sold comps.<br/>
                <strong>curve_adjusted</strong>: curve_base nudged by comps (capped ±7%).<br/>
                <strong>resale_mid/low/high</strong>: resale band used to compute max bid + profit.<br/>
                <strong>recommended_max_bid</strong>: cap that preserves profit targets after costs.<br/>
                <strong>net_profit_worst</strong>: worst-case profit at resale_low.<br/>
                <strong>computed_verdict</strong>: decision label for the listing.
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

filtered = active_df.copy()
if "hours_remaining" in filtered.columns:
    if min_hours is not None:
        filtered = filtered[filtered["hours_remaining"].fillna(0) >= min_hours]
    if max_hours is not None:
        filtered = filtered[filtered["hours_remaining"].fillna(max_hours) <= max_hours]

if group_filter != "All":
    filtered = filtered[filtered["group_id"] == group_filter]

filtered = filtered.dropna(subset=["group_id"]).copy()

if filtered.empty:
    st.info("No active listings match the current filters.")
    st.stop()


results: list[Dict[str, Any]] = []
for _, row in filtered.iterrows():
    group_id = row.get("group_id")
    year_val = _safe_int(row.get("year"))
    odo_val = row.get("odometer_numeric")
    base_estimate = interpolate_base_by_year(curves_df, group_id, year_val, odo_val)
    stats = sold_stats.loc[group_id] if group_id in sold_stats.index else None
    comps_count = int(stats["comps_count"]) if stats is not None else None
    comps_median = float(stats["comps_median"]) if stats is not None else None
    adjusted_estimate = base_estimate
    if base_estimate and comps_median:
        diff_pct = (comps_median - base_estimate) / base_estimate
        capped = max(-0.07, min(0.07, diff_pct))
        adjusted_estimate = base_estimate * (1.0 + capped)

    if adjusted_estimate is None:
        results.append(
            {
                "url": row.get("url"),
                "curve_base": None,
                "curve_adjusted": None,
                "computed_verdict": "Not Covered",
                "recommended_max_bid": None,
                "resale_mid": None,
                "net_profit_worst": None,
            }
        )
        continue

    analysis = run_curve_listing_analysis(
        row,
        adjusted_estimate,
        comps_median=comps_median,
        comps_count=comps_count,
        force_refresh=refresh_clicked,
    )
    analysis["curve_base"] = base_estimate
    analysis["curve_adjusted"] = adjusted_estimate
    analysis["comps_count"] = comps_count
    analysis["comps_median"] = comps_median
    results.append(analysis)


results_df = pd.DataFrame(results)
output = filtered.merge(results_df, on="url", how="left")

summary_html = clean_html(
    f"""
    <div class="autosniper-section">
        <div class="section-title">Restricted Listings</div>
        <div class="section-subtitle">Total records: {len(output):,}</div>
    </div>
    """
)
st.markdown(summary_html, unsafe_allow_html=True)

display_df = output.copy()
if "comps_median" not in display_df.columns:
    display_df["comps_median"] = None
if "comps_count" not in display_df.columns:
    display_df["comps_count"] = None
display_df["curve_base"] = display_df["curve_base"].apply(_format_currency)
display_df["curve_adjusted"] = display_df["curve_adjusted"].apply(_format_currency)
display_df["comps_median"] = display_df["comps_median"].apply(_format_currency)

display_columns = [
    "year",
    "make",
    "model",
    "variant",
    "odometer_reading",
    "price",
    "group_id",
    "curve_base",
    "curve_adjusted",
    "comps_count",
    "comps_median",
    "resale_mid",
    "recommended_max_bid",
    "net_profit_worst",
    "computed_verdict",
    "url",
]
available_columns = [col for col in display_columns if col in display_df.columns]
st.dataframe(display_df[available_columns], width="stretch")

st.caption(f"Last refreshed: {time.strftime('%Y-%m-%d %H:%M:%S')}")
