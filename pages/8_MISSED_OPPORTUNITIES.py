from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from shared.comps_engine import parse_currency, parse_numeric
from shared.canonical_tagging import is_canonical_eligible
from shared.curves import load_curves, interpolate_base_by_year, interpolate_price_by_km
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.parts_cost import estimate_parts_cost
from shared.repair_pricing import assess_repairs, apply_repairs_to_max_bid
from shared.repair_features import build_repair_features, serialize_tags
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro
from scripts.ai_listing_valuation import (
    MIN_NET_PROFIT_ABSOLUTE,
    MIN_NET_PROFIT_RATIO,
    _calculate_confidence,
    _calculate_downside_percent,
    _detect_risk_flags,
    _estimate_costs as estimate_costs,
    _round_to_10,
    _solve_max_bid as solve_max_bid,
    apply_platform_risk_adjustments,
)


st.set_page_config(page_title="MISSED OPPORTUNITIES", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "MISSED OPPORTUNITIES",
    "Compare sold results against curve-based estimates for the restricted universe.",
    show_logo=False,
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
        + ". Run the restricted dataset build and ensure curve data exists."
    )
    st.stop()


def money(value: object) -> str:
    try:
        if value is None or pd.isna(value):
            return "N/A"
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "N/A"


def pct(value: object) -> str:
    try:
        if value is None or pd.isna(value):
            return "N/A"
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def safe_text(value: object, default: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return default
    return text


def first_text(row: pd.Series, keys: list[str]) -> str:
    for key in keys:
        text = safe_text(row.get(key), "")
        if text:
            return text
    return ""


def format_keys(key_text: object, spare_key_text: object) -> str:
    key_value = safe_text(key_text, "")
    spare_value = safe_text(spare_key_text, "")
    if key_value and spare_value:
        return f"{key_value} / {spare_value}"
    return key_value or spare_value


def format_km(odometer_numeric: object, odometer_raw: object) -> str:
    if odometer_numeric is not None and not (isinstance(odometer_numeric, float) and pd.isna(odometer_numeric)):
        try:
            return f"{int(round(float(odometer_numeric))):,}"
        except (TypeError, ValueError):
            pass
    fallback = safe_text(odometer_raw, "")
    if fallback:
        return fallback
    return "N/A"


def glow_tier(delta: object) -> str:
    if delta is None or (isinstance(delta, float) and pd.isna(delta)):
        return "tier-na"
    try:
        delta_val = float(delta)
    except (TypeError, ValueError):
        return "tier-na"
    if delta_val >= 5000:
        return "tier-green"
    if delta_val >= 2000:
        return "tier-amber"
    return "tier-neutral"


def _to_float(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def interpolate_curve_value(
    curves_df: pd.DataFrame,
    canonical_tag: str,
    year: int | None,
    km: float | int | None,
    value_col: str,
) -> float | None:
    if curves_df.empty or not canonical_tag or year is None or km is None:
        return None
    subset = curves_df[curves_df["canonical_tag"] == canonical_tag].copy()
    subset = subset.dropna(subset=["anchor_year"])
    if subset.empty:
        return None
    anchor_years = sorted({int(y) for y in subset["anchor_year"].dropna()})
    if not anchor_years or year < anchor_years[0] or year > anchor_years[-1]:
        return None

    def _price_for_anchor(anchor_year: int) -> float | None:
        segment = subset[subset["anchor_year"] == anchor_year].copy()
        segment = segment.dropna(subset=["km_bucket", value_col])
        if segment.empty:
            return None
        segment["km_bucket"] = pd.to_numeric(segment["km_bucket"], errors="coerce")
        segment[value_col] = pd.to_numeric(segment[value_col], errors="coerce")
        segment = segment.dropna(subset=["km_bucket", value_col])
        if segment.empty:
            return None
        points = list(
            segment.sort_values("km_bucket")[["km_bucket", value_col]].itertuples(
                index=False, name=None
            )
        )
        return interpolate_price_by_km(points, km)

    lower_year = anchor_years[0]
    upper_year = anchor_years[-1]
    for start, end in zip(anchor_years, anchor_years[1:]):
        if start <= year <= end:
            lower_year = start
            upper_year = end
            break

    lower_price = _price_for_anchor(lower_year)
    upper_price = _price_for_anchor(upper_year)
    if lower_price is None and upper_price is None:
        return None
    if lower_price is None:
        return upper_price
    if upper_price is None:
        return lower_price
    if upper_year == lower_year:
        return lower_price
    ratio = (year - lower_year) / float(upper_year - lower_year)
    return lower_price + ratio * (upper_price - lower_price)


def compute_decision_metrics(
    row: pd.Series,
    resale_mid: float | None,
    *,
    include_repairs: bool,
    repair_cost_estimate: float | None,
) -> dict[str, object]:
    if resale_mid is None or resale_mid <= 0:
        return {
            "max_bid": None,
            "projected_profit_at_sold": None,
            "profit_margin_pct": None,
            "total_costs": None,
            "platform_fees": None,
            "transport": None,
            "admin_costs": None,
            "risk_buffer": None,
        }

    listing_data = row.to_dict()
    risk_flags = _detect_risk_flags(listing_data)
    downside_pct = _calculate_downside_percent(risk_flags)
    confidence_val = _calculate_confidence(listing_data, risk_flags)
    notes: list[str] = []
    downside_pct, confidence_val, risk_flags, notes = apply_platform_risk_adjustments(
        listing_data, downside_pct, confidence_val, risk_flags, notes
    )

    resale_low_val = _round_to_10(resale_mid * (1.0 - downside_pct))
    min_net_profit = max(
        MIN_NET_PROFIT_ABSOLUTE,
        MIN_NET_PROFIT_RATIO * (resale_low_val or resale_mid),
    )
    max_bid_val = solve_max_bid(resale_low_val, min_net_profit, listing_data)

    repair_assessment = assess_repairs(listing_data.get("general_condition", ""))
    if max_bid_val is not None:
        adjusted_bid, _ = apply_repairs_to_max_bid(
            int(round(max_bid_val)),
            repair_assessment,
        )
        max_bid_val = float(adjusted_bid)
    if repair_assessment.hard_avoid:
        max_bid_val = 0.0

    sold_price = _to_float(row.get("price_numeric"))
    platform_fees = transport = admin_costs = total_costs = None
    projected_profit = None
    profit_margin = None
    risk_buffer = float(repair_assessment.risk_buffer or 0)
    if sold_price is not None:
        costs_map = estimate_costs(float(sold_price), listing_data)
        platform_fees = float(costs_map.get("fees_estimate", 0.0))
        transport = float(costs_map.get("transport_estimate", 0.0))
        admin_costs = float(costs_map.get("rego_estimate", 0.0)) + float(
            costs_map.get("prep_estimate", 0.0)
        )
        repair_cost_value = float(repair_cost_estimate or 0.0) if include_repairs else 0.0
        total_costs = platform_fees + transport + admin_costs + repair_cost_value + risk_buffer
        projected_profit = resale_mid - sold_price - total_costs
        if resale_mid:
            profit_margin = (projected_profit / resale_mid) * 100

    return {
        "max_bid": max_bid_val,
        "projected_profit_at_sold": projected_profit,
        "profit_margin_pct": profit_margin,
        "total_costs": total_costs,
        "platform_fees": platform_fees,
        "transport": transport,
        "admin_costs": admin_costs,
        "risk_buffer": risk_buffer,
    }


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

sold_groups = (
    group_map_df[group_map_df["source"] == "sold"][["url", "canonical_tag", "reason_code"]]
    .rename(columns={"reason_code": "canonical_reason"})
    .drop_duplicates("url")
)
sold_df = sold_df.merge(sold_groups, on="url", how="left")
sold_df = sold_df.dropna(subset=["canonical_tag", "price_numeric"]).copy()

st.markdown(
    clean_html(
        """
        <style>
        :root{
          --bg:#070b10;
          --bg2:#0b1220;
          --cyan:#27b6ff;
          --text: rgba(255,255,255,.92);
          --muted: rgba(255,255,255,.65);
        }
        .section-card{
          background: radial-gradient(120% 140% at 15% 10%, var(--bg2) 0%, var(--bg) 65%, #04070c 100%);
          border: 1px solid rgba(39,182,255,.30);
          border-radius: 14px;
          padding: 14px 16px;
        }
        .kpi-row{
          display:flex; gap:12px; flex-wrap:wrap;
          margin-top: 8px;
        }
        .kpi{
          min-width: 210px;
          background: radial-gradient(120% 140% at 15% 10%, var(--bg2) 0%, var(--bg) 65%, #04070c 100%);
          border: 1px solid rgba(39,182,255,.55);
          border-radius: 14px;
          padding: 14px 16px;
          box-shadow: 0 0 0 1px rgba(0,0,0,.25) inset;
        }
        .kpi .k{ font-size: 11px; letter-spacing:.14em; text-transform:uppercase; color: rgba(255,255,255,.70); }
        .kpi .v{ margin-top:8px; font-size: 26px; font-weight: 900; color: var(--text); line-height:1; }
        .kpi .s{ margin-top:8px; font-size: 12px; color: var(--muted); }
        .notice{
          margin-top: 10px;
          padding: 10px 12px;
          border-radius: 12px;
          border: 1px solid rgba(39,182,255,.18);
          background: rgba(39,182,255,.08);
          color: rgba(255,255,255,.80);
          font-size: 12px;
        }
        .pattern{
          margin-top: 12px;
          display:flex; gap:10px; flex-wrap:wrap;
        }
        .chip{
          display:inline-flex;
          align-items:center;
          gap:8px;
          padding: 8px 10px;
          border-radius: 999px;
          border: 1px solid rgba(39,182,255,.20);
          background: rgba(0,0,0,.30);
          color: rgba(255,255,255,.75);
          font-size: 12px;
        }
        .group-header{
          margin-top: 14px;
          margin-bottom: 6px;
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 13px;
          font-weight: 800;
          color: rgba(255,255,255,.9);
        }
        .group-header span{
          font-size: 12px;
          font-weight: 600;
          color: rgba(255,255,255,.55);
        }
        .miss-row{
          position: relative;
          border-radius: 14px;
          padding: 8px 10px;
          margin: 8px 0;
          border: 1px solid rgba(39,182,255,.30);
          background: radial-gradient(120% 140% at 15% 10%, var(--bg2) 0%, var(--bg) 65%, #04070c 100%);
          box-shadow: 0 0 0 1px rgba(0,0,0,.25) inset;
        }
        .miss-row.top-miss{
          border-top: 3px solid rgba(44,255,154,.85);
        }
        .miss-row.subdued{
          opacity: 0.78;
          box-shadow: 0 0 0 1px rgba(0,0,0,.25) inset;
        }
        .miss-row.tier-green{
          box-shadow: 0 0 0 1px rgba(0,0,0,.25) inset, 0 0 20px rgba(44,255,154,.14);
        }
        .miss-row.tier-amber{
          box-shadow: 0 0 0 1px rgba(0,0,0,.25) inset, 0 0 16px rgba(255,196,0,.10);
        }
        .miss-row.tier-neutral{
          box-shadow: 0 0 0 1px rgba(0,0,0,.25) inset, 0 0 12px rgba(39,182,255,.08);
        }
        .miss-row.tier-na{ opacity: .92; }
        .miss-top{
          display:flex;
          align-items:flex-start;
          justify-content:space-between;
          gap: 12px;
        }
        .miss-title{
          font-size: 13px;
          font-weight: 900;
          color: rgba(255,255,255,.92);
        }
        .miss-sub{
          margin-top: 2px;
          font-size: 11px;
          color: rgba(255,255,255,.62);
        }
        .miss-metrics{
          display:flex;
          gap: 8px;
          flex-wrap:wrap;
          justify-content:flex-end;
        }
        .mm{
          min-width: 120px;
          border-radius: 12px;
          padding: 8px 10px;
          border: 1px solid rgba(39,182,255,.35);
          background: rgba(0,0,0,.30);
        }
        .mm .k{ font-size:10px; letter-spacing:.14em; text-transform:uppercase; color: rgba(255,255,255,.65); }
        .mm .v{ margin-top: 5px; font-size: 13px; font-weight: 900; color: rgba(255,255,255,.92); }
        .delta-big{
          font-size: 15px;
          font-weight: 900;
        }
        .miss-row.top-miss .delta-big{
          font-size: 17px;
        }
        .delta-green{ color: rgba(44,255,154,.95); }
        .delta-amber{ color: rgba(255,196,0,.95); }
        .delta-neutral{ color: rgba(255,255,255,.80); }
        .top-badge{
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 3px 8px;
          border-radius: 999px;
          border: 1px solid rgba(44,255,154,.6);
          background: rgba(44,255,154,.12);
          color: rgba(230,255,245,.95);
          font-size: 10px;
          letter-spacing: .12em;
          text-transform: uppercase;
          margin-left: 8px;
        }
        .action a{
          display:inline-block;
          padding: 8px 14px;
          border-radius: 999px;
          background: rgba(255,255,255,.90);
          color: #0a0f16 !important;
          text-decoration:none;
          font-weight: 800;
          letter-spacing:.08em;
          text-transform: uppercase;
          font-size: 11px;
        }
        .action a:hover{ filter: brightness(.96); }
        .small-muted{ font-size: 12px; color: rgba(255,255,255,.62); }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

allow_repairs = "general_condition" in sold_df.columns
tag_options = ["All"]
curves_df = load_curves()
allowed_tags = set(
    curves_df.get("canonical_tag", pd.Series(dtype=str))
    .dropna()
    .astype(str)
    .str.strip()
    .tolist()
)
if not allowed_tags:
    st.warning("curves.csv has no canonical tags; showing all sold tags.")
    tag_values = sorted({str(value).strip() for value in sold_df["canonical_tag"].dropna().tolist()})
    tag_options.extend([value for value in tag_values if value])
else:
    tag_values = sorted(
        {
            str(value).strip()
            for value in sold_df["canonical_tag"].dropna().tolist()
            if str(value).strip() in allowed_tags
        }
    )
    tag_options.extend([value for value in tag_values if value])

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.subheader("Missed Opportunities")
st.caption("Compare sold results against curve-based estimates for the restricted universe.")

left, right = st.columns([1.2, 1], gap="large")
with left:
    tag_choice = st.selectbox("Universe (Canonical tag)", tag_options, index=0)
    include_repairs = st.checkbox(
        "Hypothesis: repairs matter (estimate costs)",
        value=allow_repairs,
        disabled=not allow_repairs,
    )
with right:
    only_missed = st.checkbox(
        "Only show true misses (sold <= max bid)",
        value=True,
    )
    min_metric = st.slider(
        "Minimum projected profit ($)" if only_missed else "Minimum curve delta ($)",
        min_value=0,
        max_value=20000,
        value=0,
        step=250,
    )
    only_net_positive = False
    if not only_missed:
        only_net_positive = st.checkbox(
            "Only keep positive projected profit after costs",
            value=False,
        )

if not allow_repairs:
    st.markdown(
        '<div class="notice">Repair estimates unavailable: general_condition is missing.</div>',
        unsafe_allow_html=True,
    )

if allow_repairs:
    sold_df = enrich_repair_estimates(sold_df, include_cost=include_repairs)
    major_mask = sold_df["repair_tags"].fillna("").str.contains(
        "engine_mechanical|non_operational", case=False, na=False
    )
    excluded_count = int(major_mask.sum())
    sold_df = sold_df[~major_mask].copy()
else:
    excluded_count = 0

results: list[dict[str, object]] = []
for _, row in sold_df.iterrows():
    canonical_tag = safe_text(row.get("canonical_tag"), "")
    curve_key = canonical_tag
    canonical_reason = safe_text(row.get("canonical_reason"), "")
    year_val = safe_int(row.get("year"))
    odo_val = row.get("odometer_numeric")
    spec_reason = ""
    if not is_canonical_eligible(canonical_tag, canonical_reason):
        spec_reason = canonical_reason or "NOT_ELIGIBLE"
        curve_estimate = None
        curve_base = None
        trim_multiplier = None
        curve_low = None
        curve_high = None
    else:
        curve_estimate = None
        curve_base = None
        trim_multiplier = None
        curve_low = None
        curve_high = None

    curve_subset = curves_df
    if curve_key:
        curve_subset = curve_subset[curve_subset["canonical_tag"] == curve_key]

    if not spec_reason:
        curve_estimate = interpolate_base_by_year(curve_subset, curve_key, year_val, odo_val)
        curve_base = curve_estimate
        curve_low = interpolate_curve_value(curve_subset, curve_key, year_val, odo_val, "price_low")
        curve_high = interpolate_curve_value(curve_subset, curve_key, year_val, odo_val, "price_high")
    if curve_estimate is None and not spec_reason:
        spec_reason = "NOT_COVERED"

    sold_price = row.get("price_numeric")
    repair_cost = row.get("repair_cost_estimate") if include_repairs else None
    delta = None
    delta_pct = None
    if curve_estimate is not None and sold_price is not None:
        delta = curve_estimate - sold_price
        if curve_estimate > 0:
            delta_pct = (delta / curve_estimate) * 100
    net_delta = None
    if delta is not None:
        net_delta = delta - (repair_cost or 0)

    decision = compute_decision_metrics(
        row,
        curve_estimate,
        include_repairs=include_repairs,
        repair_cost_estimate=repair_cost,
    )
    max_bid = decision.get("max_bid")
    projected_profit_at_sold = decision.get("projected_profit_at_sold")
    profit_margin_pct = decision.get("profit_margin_pct")
    total_costs = decision.get("total_costs")
    platform_fees = decision.get("platform_fees")
    transport_costs = decision.get("transport")
    admin_costs = decision.get("admin_costs")
    risk_buffer = decision.get("risk_buffer")

    missed = False
    if (
        sold_price is not None
        and max_bid is not None
        and projected_profit_at_sold is not None
    ):
        missed = sold_price <= max_bid and projected_profit_at_sold > 0

    location_state = first_text(row, ["location_state", "state", "location", "yard"])
    rego_text = first_text(row, ["rego_expiry", "rego_no", "rego"])
    keys_text = format_keys(row.get("key"), row.get("spare_key"))
    risk_summary = first_text(row, ["risk_flags", "repair_decision", "repair_tags"])

    results.append(
        {
            "url": safe_text(row.get("url"), ""),
            "year": row.get("year"),
            "make": row.get("make"),
            "model": row.get("model"),
            "variant": row.get("variant"),
            "odometer_reading": row.get("odometer_reading"),
            "odometer_numeric": row.get("odometer_numeric"),
            "sold_price": sold_price,
            "canonical_tag": curve_key,
            "spec_reason": spec_reason,
            "curve_base": curve_base,
            "curve_estimate": curve_estimate,
            "curve_low": curve_low,
            "curve_high": curve_high,
            "trim_multiplier": trim_multiplier,
            "delta": delta,
            "delta_pct": delta_pct,
            "repair_cost_estimate": repair_cost,
            "repair_severity": row.get("repair_severity") if include_repairs else None,
            "repair_decision": row.get("repair_decision") if include_repairs else None,
            "net_delta": net_delta,
            "max_bid": max_bid,
            "projected_profit_at_sold": projected_profit_at_sold,
            "profit_margin_pct": profit_margin_pct,
            "total_costs": total_costs,
            "platform_fees": platform_fees,
            "transport_costs": transport_costs,
            "admin_costs": admin_costs,
            "risk_buffer": risk_buffer,
            "missed": missed,
            "date_sold": row.get("date_sold"),
            "location_state": location_state,
            "rego_text": rego_text,
            "keys_text": keys_text,
            "risk_summary": risk_summary,
            "general_condition": row.get("general_condition"),
            "repair_cost_detail": row.get("repair_cost_detail") if include_repairs else None,
        }
    )

results_df = pd.DataFrame(results)

no_curve_mask = results_df["curve_estimate"].isna() | (results_df["spec_reason"] == "NOT_COVERED")
no_curve_view = results_df[no_curve_mask].copy()
eligible_view = results_df[~no_curve_mask].copy()

if tag_choice != "All":
    eligible_view = eligible_view[eligible_view["canonical_tag"] == tag_choice]
    no_curve_view = no_curve_view[no_curve_view["canonical_tag"] == tag_choice]

view = eligible_view.copy()
if only_missed:
    view = view[view["missed"]]
if min_metric > 0:
    metric_series = view["projected_profit_at_sold"] if only_missed else view["delta"]
    view = view[metric_series.fillna(0) >= min_metric]
if only_net_positive:
    view = view[view["projected_profit_at_sold"].fillna(0) > 0]

metric_series = view["projected_profit_at_sold"] if only_missed else view["delta"]
sold_count = int(view.shape[0])
with_curve = int(eligible_view.shape[0]) if not eligible_view.empty else 0
no_curve_count = int(no_curve_view.shape[0]) if not no_curve_view.empty else 0
total_missed = float(metric_series.clip(lower=0).sum()) if sold_count else 0.0
avg_missed = float(metric_series.clip(lower=0).mean()) if sold_count else 0.0

if sold_count == 0:
    summary_line = "No listings match the current hypotheses."
elif only_missed:
    if total_missed > 0:
        summary_line = f"Yes. Total missed profit: {money(total_missed)} across {sold_count:,} listings."
    else:
        summary_line = "No. No profitable misses in the current view."
else:
    if total_missed > 0:
        summary_line = f"Curve Delta view: {money(total_missed)} across {sold_count:,} listings."
    else:
        summary_line = "Curve Delta view: no positive deltas in the current view."

st.markdown(f'<div class="notice">{summary_line}</div>', unsafe_allow_html=True)

if excluded_count:
    st.markdown(
        f'<div class="notice">Excluded {excluded_count:,} listings with major engine defects.</div>',
        unsafe_allow_html=True,
    )

st.markdown('<div class="kpi-row">', unsafe_allow_html=True)

miss_label = "Total Missed Profit" if only_missed else "Curve Delta (Total)"
miss_sub = "After fees, transport, admin, risk" + (" + repairs" if include_repairs else "")
avg_label = "Average Missed Profit" if only_missed else "Average Curve Delta"

kpi_html = f"""
<div class="kpi">
  <div class="k">{miss_label}</div>
  <div class="v">{money(total_missed)}</div>
  <div class="s">{miss_sub}</div>
</div>
<div class="kpi">
  <div class="k">{avg_label}</div>
  <div class="v">{money(avg_missed)}</div>
  <div class="s">Per vehicle (filtered view)</div>
</div>
<div class="kpi">
  <div class="k">Sold Listings</div>
  <div class="v">{sold_count:,}</div>
  <div class="s">In current view</div>
</div>
<div class="kpi">
  <div class="k">With Curve Estimate</div>
  <div class="v">{with_curve:,}</div>
  <div class="s">Coverage in current view</div>
</div>
<div class="kpi">
  <div class="k">NO_CURVE Sold</div>
  <div class="v">{no_curve_count:,}</div>
  <div class="s">Excluded from misses</div>
</div>
"""
st.markdown(clean_html(kpi_html), unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

if no_curve_count:
    with st.expander(f"NO_CURVE sold ({no_curve_count})", expanded=False):
        display_cols = [
            "year",
            "make",
            "model",
            "variant",
            "sold_price",
            "canonical_tag",
            "spec_reason",
            "url",
        ]
        existing_cols = [col for col in display_cols if col in no_curve_view.columns]
        st.dataframe(no_curve_view[existing_cols], use_container_width=True)

pattern_bits: list[str] = []
if sold_count:
    if "make" in view.columns:
        top_make = view["make"].value_counts().head(1).index[0]
        pattern_bits.append(f"Top make: {html.escape(str(top_make))}")
    if "model" in view.columns:
        top_model = view["model"].value_counts().head(1).index[0]
        pattern_bits.append(f"Top model: {html.escape(str(top_model))}")
    km_med = view["odometer_numeric"].median() if "odometer_numeric" in view.columns else None
    if km_med is not None and not pd.isna(km_med):
        pattern_bits.append(f"Median km: {int(km_med):,}")
    d_med = metric_series.clip(lower=0).median()
    if d_med is not None and not pd.isna(d_med):
        label = "Median missed profit" if only_missed else "Median curve delta"
        pattern_bits.append(f"{label}: {money(d_med)}")

if pattern_bits:
    chips = "".join([f'<div class="chip">{item}</div>' for item in pattern_bits])
    st.markdown(f'<div class="pattern">{chips}</div>', unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)

st.markdown('<div class="section-card" style="margin-top:14px;">', unsafe_allow_html=True)
st.markdown(
    "### Misses (sorted by highest projected profit)"
    if only_missed
    else "### Curve Delta View"
)

sort_choice = st.selectbox(
    "Sort",
    [
        "Projected profit (high to low)",
        "Max bid (high to low)",
        "Sold price (low to high)",
        "Odometer (low to high)",
        "Date sold (new to old)",
        "Curve delta (high to low)",
    ],
    index=0,
)

sort_df = view.copy()
if sort_choice == "Projected profit (high to low)" and "projected_profit_at_sold" in sort_df.columns:
    sort_df = sort_df.sort_values("projected_profit_at_sold", ascending=False, na_position="last")
elif sort_choice == "Max bid (high to low)" and "max_bid" in sort_df.columns:
    sort_df = sort_df.sort_values("max_bid", ascending=False, na_position="last")
elif sort_choice == "Sold price (low to high)" and "sold_price" in sort_df.columns:
    sort_df = sort_df.sort_values("sold_price", ascending=True, na_position="last")
elif sort_choice == "Odometer (low to high)" and "odometer_numeric" in sort_df.columns:
    sort_df = sort_df.sort_values("odometer_numeric", ascending=True, na_position="last")
elif sort_choice == "Date sold (new to old)" and "date_sold" in sort_df.columns:
    sort_df = sort_df.sort_values("date_sold", ascending=False, na_position="last")
elif sort_choice == "Curve delta (high to low)" and "delta" in sort_df.columns:
    sort_df = sort_df.sort_values("delta", ascending=False, na_position="last")

if sort_df.empty:
    st.info("No listings match the current hypotheses.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

limit_choice = st.selectbox("Show top", [20, 50, 100], index=0)
render_df = sort_df.head(limit_choice)

metric_field = "projected_profit_at_sold" if only_missed else "delta"
metric_values = render_df[metric_field].dropna()
top_threshold = None
low_threshold = None
if not metric_values.empty:
    top_threshold = float(metric_values.quantile(0.85))
    low_threshold = float(metric_values.quantile(0.4))

group_key = render_df.apply(
    lambda row: " ".join(
        part
        for part in [safe_text(row.get("make"), ""), safe_text(row.get("model"), "")]
        if part
    ).strip()
    or "Other",
    axis=1,
)
render_df = render_df.assign(group_key=group_key)

group_scores = (
    render_df.assign(metric_value=render_df[metric_field].fillna(0))
    .groupby("group_key")["metric_value"]
    .sum()
    .sort_values(ascending=False)
)
top_groups = group_scores.head(3).index.tolist()
render_df["group_bucket"] = render_df["group_key"].apply(
    lambda value: value if value in top_groups else "Other"
)

group_order = [group for group in top_groups if group in render_df["group_bucket"].unique()]
if "Other" in render_df["group_bucket"].unique() and "Other" not in group_order:
    group_order.append("Other")

for group in group_order:
    group_df = render_df[render_df["group_bucket"] == group].copy()
    if group_df.empty:
        continue
    group_avg = group_df[metric_field].mean()
    if pd.notna(group_avg) and group_avg >= 5000:
        group_icon = "🚨"
    elif pd.notna(group_avg) and group_avg >= 2000:
        group_icon = "⚠️"
    else:
        group_icon = "📈"
    avg_label = "avg profit" if only_missed else "avg delta"
    group_summary = f"{money(group_avg)} {avg_label} • {len(group_df):,} listings"
    st.markdown(
        f'<div class="group-header">{group_icon} {html.escape(group)} <span>{group_summary}</span></div>',
        unsafe_allow_html=True,
    )

    group_df = group_df.sort_values(metric_field, ascending=False, na_position="last")
    for _, row in group_df.iterrows():
        year = safe_int(row.get("year"))
        make = safe_text(row.get("make"), "")
        model = safe_text(row.get("model"), "")
        variant = safe_text(row.get("variant"), "")
        sold_price = row.get("sold_price")
        curve_est = row.get("curve_estimate")
        delta = row.get("delta")
        url = safe_text(row.get("url"), "")
        date_sold = safe_text(row.get("date_sold"), "")

        metric_value = row.get(metric_field)
        tier = glow_tier(metric_value)
        row_classes = [tier]
        metric_val = None
        if metric_value is None or (isinstance(metric_value, float) and pd.isna(metric_value)):
            metric_class = "delta-neutral"
            metric_text = "N/A"
        else:
            metric_val = float(metric_value)
            if metric_val >= 5000:
                metric_class = "delta-green"
            elif metric_val >= 2000:
                metric_class = "delta-amber"
            else:
                metric_class = "delta-neutral"
            metric_text = money(metric_val)
            if top_threshold is not None and metric_val >= top_threshold:
                row_classes.append("top-miss")
            if low_threshold is not None and metric_val <= low_threshold:
                row_classes.append("subdued")

        delta_val = _to_float(delta)
        delta_text = money(delta_val) if delta_val is not None else "N/A"
        max_bid = row.get("max_bid")
        profit_at_sold = row.get("projected_profit_at_sold")
        profit_margin = row.get("profit_margin_pct")

        title = " ".join([part for part in [str(year) if year else "", make, model] if part]).strip()
        sub = " • ".join([part for part in [variant, f"Sold: {date_sold}" if date_sold else ""] if part])
        top_badge = ""
        if metric_val is not None and top_threshold is not None and metric_val >= top_threshold:
            top_label = "Top profit" if only_missed else "Top delta"
            top_badge = f'<span class="top-badge">{top_label}</span>'

        row_html = f"""
        <div class="miss-row {' '.join(row_classes)}">
          <div class="miss-top">
            <div>
              <div class="miss-title">{html.escape(title)}{top_badge}</div>
              <div class="miss-sub">{html.escape(sub)}</div>
            </div>
            <div class="miss-metrics">
              <div class="mm"><div class="k">Sold</div><div class="v">{money(sold_price)}</div></div>
              <div class="mm"><div class="k">Max bid</div><div class="v">{money(max_bid)}</div></div>
              <div class="mm"><div class="k">{"Profit" if only_missed else "Curve delta"}</div><div class="v delta-big {metric_class}">{metric_text}</div></div>
              <div class="mm"><div class="k">Profit %</div><div class="v">{pct(profit_margin)}</div></div>
              <div class="mm"><div class="k">Curve delta</div><div class="v">{delta_text}</div></div>
            </div>
          </div>
        </div>
        """
        st.markdown(clean_html(row_html), unsafe_allow_html=True)

        with st.expander("Details", expanded=False):
            cols = st.columns(3)
            with cols[0]:
                st.markdown("**Curve (resale mid)**")
                st.write(money(curve_est))
                st.markdown("**Sold price**")
                st.write(money(sold_price))
                st.markdown("**Max bid (Stage 6)**")
                st.write(money(row.get("max_bid")))
                st.markdown("**Projected profit at sold**")
                st.write(money(row.get("projected_profit_at_sold")))
                st.markdown("**Profit margin %**")
                st.write(pct(row.get("profit_margin_pct")))
            with cols[1]:
                st.markdown("**Total costs**")
                st.write(money(row.get("total_costs")))
                st.markdown("**Platform fees**")
                st.write(money(row.get("platform_fees")))
                st.markdown("**Transport**")
                st.write(money(row.get("transport_costs")))
                st.markdown("**Admin (rego + prep)**")
                st.write(money(row.get("admin_costs")))
                st.markdown("**Risk buffer**")
                st.write(money(row.get("risk_buffer")))
                if include_repairs:
                    st.markdown("**Repair estimate**")
                    st.write(money(row.get("repair_cost_estimate")))
            with cols[2]:
                st.markdown("**Spec reason**")
                st.write(safe_text(row.get("spec_reason"), "N/A"))
                st.markdown("**Curve delta**")
                st.write(delta_text)
                st.markdown("**Delta %**")
                st.write(pct(row.get("delta_pct")))
                if include_repairs:
                    st.markdown("**Repair decision**")
                    st.write(safe_text(row.get("repair_decision"), "N/A"))
                    st.markdown("**Repair severity**")
                    st.write(safe_text(row.get("repair_severity"), "N/A"))
                st.markdown("**Risk / notes**")
                st.write(safe_text(row.get("risk_summary"), "N/A"))
                condition_text = safe_text(row.get("general_condition"), "")
                if condition_text:
                    st.write(condition_text)
                st.markdown("**Location / rego / keys**")
                st.write(safe_text(row.get("location_state"), "N/A"))
                st.write(safe_text(row.get("rego_text"), "N/A"))
                st.write(safe_text(row.get("keys_text"), "N/A"))
                st.markdown("**Listing**")
                if url:
                    st.markdown(f"[Open listing]({url})")
                else:
                    st.write("N/A")

st.markdown("</div>", unsafe_allow_html=True)
