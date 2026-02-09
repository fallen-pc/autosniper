from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from shared.comps_engine import parse_currency, parse_numeric
from shared.canonical_tagging import is_canonical_eligible
from shared.curves import curve_dataset_name, curve_model, load_curves, interpolate_base_by_year
from shared.data_loader import dataset_path, ensure_datasets_available
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
from shared.pipe_keys import looks_like_pipe_key, parse_pipe_key
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro
from shared.trim_multipliers import apply_trim_multiplier, load_trim_multipliers


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
    curve_dataset_name(),
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
    if curve_model() == "v2" and "canonical_tag" in df.columns:
        df["group_id"] = df["canonical_tag"]
    return df


curves_df = load_curves()
sold_df = load_sold_data()
group_map_df = load_group_map()
spec = load_spec()
spec_error = get_spec_error(spec)
if spec_error == "pyyaml_missing":
    st.warning("Spec checks disabled: install `pyyaml` to enable config/spec_v1.yaml validation.")
    spec = {}

trim_config = load_trim_multipliers()
if trim_config.get("_error") == "pyyaml_missing":
    st.warning("Trim multipliers disabled: install `pyyaml` to enable config/trim_multipliers.yaml.")
    trim_config = {}

spec_issues = []
if spec and not curves_df.empty:
    sample_group = curves_df["group_id"].dropna().iloc[0] if "group_id" in curves_df.columns else None
    if not looks_like_pipe_key(sample_group):
        spec_issues = validate_curve_requirements(spec, curves_df)
if spec_issues:
    issue_preview = "\n".join(spec_issues[:10])
    extra = "" if len(spec_issues) <= 10 else f"\n...and {len(spec_issues) - 10} more"
    st.warning(f"Spec/curve issues detected:\n{issue_preview}{extra}")

sold_groups = (
    group_map_df[group_map_df["source"] == "sold"][["url", "group_id", "canonical_tag", "reason_code"]]
    .rename(columns={"reason_code": "canonical_reason"})
    .drop_duplicates("url")
)
sold_df = sold_df.merge(sold_groups, on="url", how="left")
curve_key_col = "canonical_tag" if curve_model() == "v2" else "group_id"
sold_df = sold_df.dropna(subset=[curve_key_col, "price_numeric"]).copy()

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
group_ids = ["All"]
if curve_model() == "v2" and "canonical_tag" in sold_df.columns:
    group_values = sorted({str(value).strip() for value in sold_df["canonical_tag"].dropna().tolist()})
    group_ids.extend([value for value in group_values if value])
elif "group_id" in sold_df.columns:
    group_values = sorted({str(value).strip() for value in sold_df["group_id"].dropna().tolist()})
    group_ids.extend([value for value in group_values if value])

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.subheader("Missed Opportunities")
st.caption("Compare sold results against curve-based estimates for the restricted universe.")

left, right = st.columns([1.2, 1], gap="large")
with left:
    group_label = "Universe (Canonical tag)" if curve_model() == "v2" else "Universe (Group ID)"
    group_choice = st.selectbox(group_label, group_ids, index=0)
    include_repairs = st.checkbox(
        "Hypothesis: repairs matter (estimate costs)",
        value=allow_repairs,
        disabled=not allow_repairs,
    )
with right:
    only_sold_below = st.checkbox(
        "Hypothesis: only misses when sold below curve",
        value=True,
    )
    min_delta = st.slider(
        "Hypothesis: misses above $X are meaningful",
        min_value=0,
        max_value=20000,
        value=0,
        step=250,
    )
    only_net_positive = False
    if include_repairs:
        only_net_positive = st.checkbox(
            "Hypothesis: still positive after repairs",
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
    group_id_value = row.get("group_id")
    group_id = safe_text(group_id_value, "")
    canonical_tag = row.get("canonical_tag")
    curve_key = safe_text(canonical_tag, "") if curve_model() == "v2" else group_id
    canonical_reason = safe_text(row.get("canonical_reason"), "")
    year_val = safe_int(row.get("year"))
    odo_val = row.get("odometer_numeric")
    spec_reason = ""
    series_key = None
    if not is_canonical_eligible(canonical_tag, canonical_reason):
        spec_reason = canonical_reason or "NOT_ELIGIBLE"
        curve_estimate = None
        curve_base = None
        trim_multiplier = None
    else:
        curve_estimate = None
        curve_base = None
        trim_multiplier = None
    if curve_model() != "v2":
        parsed = parse_pipe_key(group_id)
        if parsed:
            _, _, series_key, _ = parsed
        elif not spec_reason:
            lookup_id = canonical_tag or group_id
            spec_group = get_group_spec(spec, lookup_id) if spec else None
            if spec and not spec_group:
                spec_reason = "UNKNOWN_GROUP_MAPPING"
            elif spec_group:
                series_key, spec_reason = resolve_series_for_year(spec, lookup_id, year_val)
                if not spec_reason and series_key and not is_series_allowed(spec_group, series_key):
                    spec_reason = "SERIES_NOT_COVERED"

    curve_subset = curves_df
    if curve_key:
        curve_subset = curve_subset[curve_subset["group_id"] == curve_key]
    if series_key and not curve_subset.empty:
        curve_subset = curve_subset[curve_subset["series"] == series_key]
        if curve_subset.empty and not spec_reason:
            spec_reason = "SERIES_NOT_COVERED"

    if not spec_reason:
        curve_estimate = interpolate_base_by_year(curve_subset, curve_key, year_val, odo_val)
        curve_base = curve_estimate
        if curve_estimate is not None:
            trim_text = first_text(row, ["trim", "variant", "series", "model"])
            curve_estimate, trim_multiplier = apply_trim_multiplier(
                curve_estimate,
                curve_key,
                trim_text,
                odo_val,
                trim_config,
            )
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
            "group_id": curve_key,
            "spec_series": series_key,
            "spec_reason": spec_reason,
            "curve_base": curve_base,
            "curve_estimate": curve_estimate,
            "trim_multiplier": trim_multiplier,
            "delta": delta,
            "delta_pct": delta_pct,
            "repair_cost_estimate": repair_cost,
            "repair_severity": row.get("repair_severity") if include_repairs else None,
            "repair_decision": row.get("repair_decision") if include_repairs else None,
            "net_delta": net_delta,
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

view = results_df.copy()
if group_choice != "All":
    view = view[view["group_id"] == group_choice]
if only_sold_below:
    view = view[view["delta"].fillna(0) > 0]
if min_delta > 0:
    view = view[view["delta"].fillna(0) >= min_delta]
if only_net_positive:
    view = view[view["net_delta"].fillna(0) > 0]

delta_series = view["net_delta"] if include_repairs else view["delta"]
sold_count = int(view.shape[0])
with_curve = int(view["curve_estimate"].notna().sum()) if sold_count else 0
total_missed = float(delta_series.clip(lower=0).sum()) if sold_count else 0.0
avg_missed = float(delta_series.clip(lower=0).mean()) if sold_count else 0.0

if sold_count == 0:
    summary_line = "No listings match the current hypotheses."
elif total_missed > 0:
    summary_line = f"Yes. Estimated missed margin: {money(total_missed)} across {sold_count:,} listings."
else:
    summary_line = "No. No positive deltas in the current view."

st.markdown(f'<div class="notice">{summary_line}</div>', unsafe_allow_html=True)

if excluded_count:
    st.markdown(
        f'<div class="notice">Excluded {excluded_count:,} listings with major engine defects.</div>',
        unsafe_allow_html=True,
    )

st.markdown('<div class="kpi-row">', unsafe_allow_html=True)

miss_label = "Total Missed (Net Delta)" if include_repairs else "Total Missed (Delta > 0)"
miss_sub = "After repair estimates" if include_repairs else "Curve estimate minus sold price"

kpi_html = f"""
<div class="kpi">
  <div class="k">{miss_label}</div>
  <div class="v">{money(total_missed)}</div>
  <div class="s">{miss_sub}</div>
</div>
<div class="kpi">
  <div class="k">Average Miss</div>
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
"""
st.markdown(clean_html(kpi_html), unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

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
    d_med = delta_series.clip(lower=0).median()
    if d_med is not None and not pd.isna(d_med):
        pattern_bits.append(f"Median miss: {money(d_med)}")

if pattern_bits:
    chips = "".join([f'<div class="chip">{item}</div>' for item in pattern_bits])
    st.markdown(f'<div class="pattern">{chips}</div>', unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)

st.markdown('<div class="section-card" style="margin-top:14px;">', unsafe_allow_html=True)
st.markdown("### Misses (sorted by highest delta)")

sort_choice = st.selectbox(
    "Sort",
    ["Delta (high to low)", "Sold price (low to high)", "Odometer (low to high)", "Date sold (new to old)"],
    index=0,
)

sort_df = view.copy()
if sort_choice == "Delta (high to low)" and "delta" in sort_df.columns:
    sort_df = sort_df.sort_values("delta", ascending=False, na_position="last")
elif sort_choice == "Sold price (low to high)" and "sold_price" in sort_df.columns:
    sort_df = sort_df.sort_values("sold_price", ascending=True, na_position="last")
elif sort_choice == "Odometer (low to high)" and "odometer_numeric" in sort_df.columns:
    sort_df = sort_df.sort_values("odometer_numeric", ascending=True, na_position="last")
elif sort_choice == "Date sold (new to old)" and "date_sold" in sort_df.columns:
    sort_df = sort_df.sort_values("date_sold", ascending=False, na_position="last")

if sort_df.empty:
    st.info("No listings match the current hypotheses.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

limit_choice = st.selectbox("Show top", [20, 50, 100], index=0)
render_df = sort_df.head(limit_choice)

delta_values = render_df["delta"].dropna()
top_threshold = None
low_threshold = None
if not delta_values.empty:
    top_threshold = float(delta_values.quantile(0.85))
    low_threshold = float(delta_values.quantile(0.4))

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
    render_df.assign(delta_value=render_df["delta"].fillna(0))
    .groupby("group_key")["delta_value"]
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
    group_avg = group_df["delta"].mean()
    if pd.notna(group_avg) and group_avg >= 5000:
        group_icon = "🚨"
    elif pd.notna(group_avg) and group_avg >= 2000:
        group_icon = "⚠️"
    else:
        group_icon = "📈"
    group_summary = f"{money(group_avg)} avg miss • {len(group_df):,} listings"
    st.markdown(
        f'<div class="group-header">{group_icon} {html.escape(group)} <span>{group_summary}</span></div>',
        unsafe_allow_html=True,
    )

    group_df = group_df.sort_values("delta", ascending=False, na_position="last")
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

        tier = glow_tier(delta)
        row_classes = [tier]
        delta_val = None
        if delta is None or (isinstance(delta, float) and pd.isna(delta)):
            delta_class = "delta-neutral"
            delta_text = "N/A"
        else:
            delta_val = float(delta)
            if delta_val >= 5000:
                delta_class = "delta-green"
            elif delta_val >= 2000:
                delta_class = "delta-amber"
            else:
                delta_class = "delta-neutral"
            delta_text = money(delta_val)
            if top_threshold is not None and delta_val >= top_threshold:
                row_classes.append("top-miss")
            if low_threshold is not None and delta_val <= low_threshold:
                row_classes.append("subdued")

        title = " ".join([part for part in [str(year) if year else "", make, model] if part]).strip()
        sub = " • ".join([part for part in [variant, f"Sold: {date_sold}" if date_sold else ""] if part])
        top_badge = ""
        if delta_val is not None and top_threshold is not None and delta_val >= top_threshold:
            top_badge = '<span class="top-badge">Top miss</span>'

        row_html = f"""
        <div class="miss-row {' '.join(row_classes)}">
          <div class="miss-top">
            <div>
              <div class="miss-title">{html.escape(title)}{top_badge}</div>
              <div class="miss-sub">{html.escape(sub)}</div>
            </div>
            <div class="miss-metrics">
              <div class="mm"><div class="k">Sold</div><div class="v">{money(sold_price)}</div></div>
              <div class="mm"><div class="k">Curve</div><div class="v">{money(curve_est)}</div></div>
              <div class="mm"><div class="k">Delta</div><div class="v delta-big {delta_class}">{delta_text}</div></div>
            </div>
          </div>
        </div>
        """
        st.markdown(clean_html(row_html), unsafe_allow_html=True)

        with st.expander("Details", expanded=False):
            cols = st.columns(3)
            with cols[0]:
                st.markdown("**Curve estimate**")
                st.write(money(curve_est))
                st.markdown("**Sold price**")
                st.write(money(sold_price))
                st.markdown("**Delta (curve - sold)**")
                st.write(delta_text)
                if include_repairs:
                    st.markdown("**Net delta (after repairs)**")
                    st.write(money(row.get("net_delta")))
                    st.markdown("**Repair estimate**")
                    st.write(money(row.get("repair_cost_estimate")))
            with cols[1]:
                st.markdown("**Spec series / reason**")
                st.write(safe_text(row.get("spec_series"), "N/A"))
                st.write(safe_text(row.get("spec_reason"), "N/A"))
                st.markdown("**Delta %**")
                st.write(pct(row.get("delta_pct")))
                if include_repairs:
                    st.markdown("**Repair decision**")
                    st.write(safe_text(row.get("repair_decision"), "N/A"))
                    st.markdown("**Repair severity**")
                    st.write(safe_text(row.get("repair_severity"), "N/A"))
            with cols[2]:
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
