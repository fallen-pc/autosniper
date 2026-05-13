from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from shared.comps_engine import parse_currency, parse_numeric
from shared.canonical_tagging import is_canonical_eligible
from shared.curves import (
    interpolate_base_by_year,
    interpolate_price_by_km,
    list_curve_tags,
    load_curves,
    resolve_curve_canonical_tag,
)
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.global_filters import apply_global_sidebar_filters, render_global_sidebar_filters
from shared.parts_cost import estimate_parts_cost
from shared.repair_features import build_repair_features, serialize_tags
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro
from shared.missed_opportunities import compute_decision_metrics


st.set_page_config(page_title="MISSED OPPORTUNITIES", layout="wide")
render_global_sidebar_filters()
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


def build_metric_box(label: str, value: str, subtext: str | None = None, class_name: str | None = None) -> str:
    class_attr = f"metric-box {class_name}".strip() if class_name else "metric-box"
    sub_html = f'<div class="metric-sub">{html.escape(subtext)}</div>' if subtext else ""
    return (
        f'<div class="{class_attr}">'
        f'<div class="metric-label">{html.escape(label)}</div>'
        f'<div class="metric-value">{html.escape(value)}</div>'
        f"{sub_html}"
        "</div>"
    )


def profit_tier_class(value: object) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "profit-tier-low"
    if numeric >= 25:
        return "profit-tier-high"
    if numeric >= 10:
        return "profit-tier-mid"
    return "profit-tier-low"


def metric_tone_class(value: object) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "price-flat"
    if numeric >= 2000:
        return "price-up"
    if numeric > 0:
        return "price-flat"
    return "price-down"


def badge_tone(value: str) -> str:
    normalized = safe_text(value, "").strip().lower()
    if normalized == "high":
        return "badge-high"
    if normalized == "medium":
        return "badge-medium"
    if normalized == "low":
        return "badge-low"
    return "badge-neutral"


def confidence_badges_html(curve_status: str, miss_status: str, risk_status: str) -> str:
    badges = []
    for label, value in [
        ("Curve Coverage", curve_status),
        ("Historical Status", miss_status),
        ("Risk Level", risk_status),
    ]:
        badges.append(
            '<div class="confidence-badge '
            + badge_tone(value)
            + '">'
            + f'<span class="confidence-badge-label">{html.escape(label)}</span>'
            + f'<span class="confidence-badge-value">{html.escape(value.upper())}</span>'
            + "</div>"
        )
    return f'<div class="confidence-badge-row">{"".join(badges)}</div>'


def sold_action_parts(row: pd.Series) -> tuple[str, str, str]:
    missed = bool(row.get("missed"))
    profit = _to_float(row.get("projected_profit_at_sold"))
    sold_price = _to_float(row.get("sold_price"))
    max_bid = _to_float(row.get("max_bid"))
    if missed:
        return "Missed buy", "Good historical deal", "verdict-good"
    if profit is not None and profit > 0 and sold_price is not None and max_bid is not None and sold_price > max_bid:
        return "Sold above max", "Watch only", "verdict-marginal"
    if profit is not None and profit > 0:
        return "Positive but blocked", "Review", "verdict-marginal"
    return "No buy", "Avoid", "verdict-avoid"


def risk_level(row: pd.Series) -> str:
    repair_decision = safe_text(row.get("repair_decision"), "").lower()
    risk_summary = safe_text(row.get("risk_summary"), "").lower()
    if any(token in repair_decision for token in ["avoid", "hard"]) or any(
        token in risk_summary for token in ["engine", "structural", "write-off", "wovr"]
    ):
        return "High"
    if any(token in repair_decision for token in ["marginal", "repair"]) or risk_summary:
        return "Medium"
    return "Low"


def render_detail_value(label: str, value: str) -> None:
    st.markdown(f"**{label}**")
    st.write(value)


def render_sold_analysis_card(
    row: pd.Series,
    *,
    only_missed: bool,
    include_repairs: bool,
    metric_field: str,
    top_threshold: float | None,
    low_threshold: float | None,
) -> None:
    year = safe_int(row.get("year"))
    make = safe_text(row.get("make"), "")
    model = safe_text(row.get("model"), "")
    variant = safe_text(row.get("variant"), "")
    title = " ".join([part for part in [str(year) if year else "", make, model, variant] if part]).strip()
    title = title or "Sold listing"
    location = safe_text(row.get("location_state"), "")
    location_badge = f"({location})" if location else ""
    canonical_tag = safe_text(row.get("canonical_tag"), "")
    sold_date = safe_text(row.get("date_sold"), "")
    header_meta = " | ".join(
        part
        for part in [
            f"Tag {canonical_tag}" if canonical_tag else "",
            f"Sold {sold_date}" if sold_date else "Sold listing",
        ]
        if part
    )

    action_label, verdict_label, verdict_class = sold_action_parts(row)
    profit_class = profit_tier_class(row.get("profit_margin_pct"))
    metric_value = row.get(metric_field)
    metric_label = "Profit at sold price" if only_missed else "Curve delta"
    metric_sub = "Historical sold result" if only_missed else "Curve estimate minus sold price"
    top_badge = ""
    metric_numeric = _to_float(metric_value)
    if metric_numeric is not None and top_threshold is not None and metric_numeric >= top_threshold:
        top_badge = '<div class="verdict-pill top-buy-pill">TOP HISTORICAL DEAL</div>'
    subdued_class = ""
    if metric_numeric is not None and low_threshold is not None and metric_numeric <= low_threshold:
        subdued_class = " subdued"

    sold_price = row.get("sold_price")
    max_bid = row.get("max_bid")
    curve_est = row.get("curve_estimate")
    delta = row.get("delta")
    profit_margin = row.get("profit_margin_pct")
    expected_auction = row.get("expected_auction_price")
    url = safe_text(row.get("url"), "")
    odometer = format_km(row.get("odometer_numeric"), row.get("odometer_reading"))
    miss_classification = safe_text(row.get("miss_classification"), "unclassified")
    repair_decision = safe_text(row.get("repair_decision"), "N/A")
    risk_status = risk_level(row)
    miss_status = "High" if bool(row.get("missed")) else "Medium" if _to_float(row.get("projected_profit_at_sold")) else "Low"
    curve_status = "High" if _to_float(curve_est) is not None else "Low"

    card_html = "".join(
        [
            f'<div class="vehicle-card {verdict_class} {profit_class}{subdued_class}">',
            '<div class="card-top">',
            '<div class="vehicle-title-block">',
            '<div class="vehicle-title">',
            f'<span class="vehicle-title-text">{html.escape(title)}</span>',
            f'<span class="vehicle-location">{html.escape(location_badge)}</span>' if location_badge else "",
            "</div>",
            f'<div class="card-top-meta">{html.escape(header_meta)}</div>' if header_meta else "",
            "</div>",
            '<div class="card-top-right">',
            f'<div class="verdict-pill action-pill">{html.escape(action_label)}</div>',
            top_badge,
            f'<div class="verdict-pill {verdict_class}-pill support-pill">{html.escape(verdict_label)}</div>',
            '<div class="card-actions">',
            f'<a href="{html.escape(url)}" target="_blank">Open</a>'
            if url and not url.lower().lstrip().startswith("javascript:")
            else "",
            "</div>",
            "</div>",
            "</div>",
            '<div class="card-metrics">',
            build_metric_box("Sold price", money(sold_price)),
            build_metric_box("Max bid limit", money(max_bid), "Rebuilt from AI rules"),
            build_metric_box(metric_label, money(metric_value), metric_sub, metric_tone_class(metric_value)),
            build_metric_box("Profit %", pct(profit_margin)),
            build_metric_box("Expected resale", money(curve_est), "Curve resale mid"),
            build_metric_box("Expected auction", money(expected_auction)),
            build_metric_box("Curve delta", money(delta)),
            build_metric_box("Underbid %", pct(row.get("underbid_pct"))),
            build_metric_box("Odometer", f"{odometer} km" if odometer != "N/A" and "km" not in odometer.lower() else odometer),
            build_metric_box("Classification", miss_classification),
            "</div>",
            confidence_badges_html(curve_status, miss_status, risk_status),
            '<div class="chip-row">',
            f'<span class="chip">Rego: {html.escape(safe_text(row.get("rego_text"), "N/A"))}</span>',
            f'<span class="chip">Keys: {html.escape(safe_text(row.get("keys_text"), "N/A"))}</span>',
            f'<span class="chip {("warn" if risk_status == "Medium" else "danger" if risk_status == "High" else "good")}">Risk: {html.escape(risk_status)}</span>',
            f'<span class="chip">Repair: {html.escape(repair_decision)}</span>' if include_repairs else "",
            "</div>",
            "</div>",
        ]
    )
    st.markdown(clean_html(card_html), unsafe_allow_html=True)

    overview_tab, curve_tab, costs_tab, condition_tab = st.tabs(
        ["Overview", "Curve", "Costs", "Condition"]
    )
    with overview_tab:
        cols = st.columns(3)
        with cols[0]:
            render_detail_value("Sold price", money(sold_price))
            render_detail_value("Max bid limit", money(max_bid))
            render_detail_value("Profit at sold", money(row.get("projected_profit_at_sold")))
        with cols[1]:
            render_detail_value("Miss classification", miss_classification)
            render_detail_value("Profit margin", pct(profit_margin))
            render_detail_value("Underbid", pct(row.get("underbid_pct")))
        with cols[2]:
            render_detail_value("Location", safe_text(row.get("location_state"), "N/A"))
            render_detail_value("Rego", safe_text(row.get("rego_text"), "N/A"))
            render_detail_value("Keys", safe_text(row.get("keys_text"), "N/A"))
    with curve_tab:
        cols = st.columns(3)
        with cols[0]:
            render_detail_value("Curve resale mid", money(curve_est))
            render_detail_value("Curve low", money(row.get("curve_low")))
            render_detail_value("Curve high", money(row.get("curve_high")))
        with cols[1]:
            render_detail_value("Sold price", money(sold_price))
            render_detail_value("Curve delta", money(delta))
            render_detail_value("Delta %", pct(row.get("delta_pct")))
        with cols[2]:
            render_detail_value("Canonical tag", canonical_tag or "N/A")
            render_detail_value("Spec reason", safe_text(row.get("spec_reason"), "N/A"))
            render_detail_value("Expected auction", money(expected_auction))
    with costs_tab:
        cols = st.columns(3)
        with cols[0]:
            render_detail_value("Total costs", money(row.get("total_costs")))
            render_detail_value("Platform fees", money(row.get("platform_fees")))
            render_detail_value("Transport", money(row.get("transport_costs")))
        with cols[1]:
            render_detail_value("Admin", money(row.get("admin_costs")))
            render_detail_value("Risk buffer", money(row.get("risk_buffer")))
            render_detail_value("Repair estimate", money(row.get("repair_cost_estimate")))
        with cols[2]:
            render_detail_value("Projected profit at sold", money(row.get("projected_profit_at_sold")))
            render_detail_value("Max bid", money(max_bid))
            render_detail_value("Sold vs max bid", "Sold inside max bid" if bool(row.get("missed")) else "Sold above max bid or no profit")
    with condition_tab:
        render_detail_value("Risk / notes", safe_text(row.get("risk_summary"), "N/A"))
        if include_repairs:
            render_detail_value("Repair decision", repair_decision)
            render_detail_value("Repair severity", safe_text(row.get("repair_severity"), "N/A"))
            render_detail_value("Repair detail", safe_text(row.get("repair_cost_detail"), "N/A"))
        condition_text = safe_text(row.get("general_condition"), "")
        if condition_text:
            st.markdown("**Condition text**")
            st.write(condition_text)
        st.markdown("**Listing**")
        if url:
            st.markdown(f"[Open listing]({url})")
        else:
            st.write("N/A")


def interpolate_curve_value(
    curves_df: pd.DataFrame,
    canonical_tag: str,
    year: int | None,
    km: float | int | None,
    value_col: str,
) -> float | None:
    curve_tag = resolve_curve_canonical_tag(canonical_tag)
    if curves_df.empty or not curve_tag or year is None or km is None:
        return None
    subset = curves_df[curves_df["canonical_tag"] == curve_tag].copy()
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


def compute_underbid_pct(sold_price: object, max_bid: object) -> float | None:
    sold_val = _to_float(sold_price)
    max_bid_val = _to_float(max_bid)
    if sold_val is None or max_bid_val is None or max_bid_val <= 0:
        return None
    return ((max_bid_val - sold_val) / max_bid_val) * 100.0


def classify_miss_reason(row: pd.Series) -> str:
    spec_reason = safe_text(row.get("spec_reason"), "")
    if spec_reason:
        return "not covered"

    sold_price = _to_float(row.get("sold_price"))
    max_bid = _to_float(row.get("max_bid"))
    curve_estimate = _to_float(row.get("curve_estimate"))
    curve_high = _to_float(row.get("curve_high"))
    projected_profit = _to_float(row.get("projected_profit_at_sold"))
    delta_pct = _to_float(row.get("delta_pct"))
    risk_buffer = max(_to_float(row.get("risk_buffer")) or 0.0, 0.0)
    repair_cost = max(_to_float(row.get("repair_cost_estimate")) or 0.0, 0.0)
    underbid_pct = _to_float(row.get("underbid_pct"))
    cost_drag = risk_buffer + repair_cost

    if sold_price is None or curve_estimate is None:
        return "unclassified"

    if curve_high is not None and sold_price > (curve_high * 1.05):
        return "auction price spike"

    if max_bid is not None and sold_price > max_bid:
        bid_gap_pct = ((sold_price - max_bid) / max_bid * 100.0) if max_bid > 0 else None
        if bid_gap_pct is not None and bid_gap_pct <= 5.0:
            return "bidding delay"
        if cost_drag > 0 and (curve_estimate - sold_price) > 0 and cost_drag >= (curve_estimate - sold_price) * 0.35:
            return "risk deduction too large"
        if delta_pct is not None and delta_pct >= 12.0:
            return "curve too conservative"
        return "auction price spike"

    if projected_profit is not None and projected_profit > 0:
        if underbid_pct is not None and underbid_pct <= 5.0:
            return "bidding delay"
        if cost_drag > 0 and (curve_estimate - sold_price) > 0 and cost_drag >= (curve_estimate - sold_price) * 0.35:
            return "risk deduction too large"
        if delta_pct is not None and delta_pct <= 8.0:
            return "curve too conservative"
        return "bidding delay"

    if cost_drag > 0:
        return "risk deduction too large"
    return "curve too conservative"


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
          border-radius: 16px;
          padding: 16px;
        }
        .kpi-row{
          display:flex; gap:12px; flex-wrap:wrap;
          margin-top: 8px;
        }
        .kpi{
          min-width: 210px;
          background: radial-gradient(120% 140% at 15% 10%, var(--bg2) 0%, var(--bg) 65%, #04070c 100%);
          border: 1px solid rgba(39,182,255,.55);
          border-radius: 16px;
          padding: 16px;
          box-shadow: 0 0 0 1px rgba(0,0,0,.25) inset;
        }
        .kpi .k{ font-size: 11px; letter-spacing:.14em; text-transform:uppercase; color: rgba(255,255,255,.70); }
        .kpi .v{ margin-top:8px; font-size: 26px; font-weight: 900; color: var(--text); line-height:1; }
        .kpi .s{ margin-top:8px; font-size: 12px; color: var(--muted); }
        .notice{
          margin-top: 10px;
          padding: 12px 14px;
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
        .class-badge{
          display: inline-flex;
          align-items: center;
          padding: 3px 8px;
          border-radius: 999px;
          border: 1px solid rgba(39,182,255,.24);
          background: rgba(39,182,255,.10);
          color: rgba(255,255,255,.82);
          font-size: 10px;
          letter-spacing: .08em;
          text-transform: uppercase;
          margin-top: 6px;
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
          border-radius: 16px;
          padding: 12px;
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
          padding: 10px 12px;
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
        .vehicle-card {
          --card-glow: 0 0 0 rgba(0, 0, 0, 0);
          --card-hover: 0 0 0 rgba(0, 0, 0, 0);
          background: linear-gradient(180deg, #08121d 0%, #0b0f14 30%, #0b0f14 100%);
          border: 1px solid rgba(39, 182, 255, 0.35);
          border-top: 3px solid var(--cyan);
          border-radius: 16px;
          padding: 0.9rem 1rem 0.85rem;
          margin: 0.8rem 0 0.45rem;
          box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.25), var(--card-glow), var(--card-hover);
          transition: box-shadow 0.15s ease, transform 0.15s ease;
        }
        .vehicle-card:hover {
          --card-hover: 0 0 12px rgba(39, 182, 255, 0.18);
          transform: translateY(-1px);
        }
        .vehicle-card.profit-tier-high {
          --card-glow: 0 0 14px rgba(44, 255, 154, 0.28);
        }
        .vehicle-card.subdued {
          opacity: .82;
        }
        .card-top {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          justify-content: space-between;
          gap: 0.6rem;
          padding-bottom: 0.3rem;
          border-bottom: 1px solid rgba(39, 182, 255, 0.16);
        }
        .vehicle-title-block {
          display: flex;
          flex-direction: column;
          gap: 0.1rem;
          min-width: 220px;
        }
        .vehicle-title {
          display: flex;
          align-items: baseline;
          gap: 0.4rem;
          font-size: 1.24rem;
          font-weight: 800;
          line-height: 1;
          color: rgba(255,255,255,.92);
        }
        .vehicle-title-text {
          flex: 1 1 auto;
          min-width: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .vehicle-location {
          flex: 0 0 auto;
          font-size: 0.72rem;
          font-weight: 600;
          color: rgba(255, 255, 255, 0.6);
        }
        .card-top-meta {
          font-size: 0.56rem;
          text-transform: uppercase;
          letter-spacing: 0.12em;
          color: rgba(255, 255, 255, 0.45);
        }
        .card-top-right {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          flex-wrap: wrap;
          justify-content: flex-end;
        }
        .card-actions a {
          display: inline-flex;
          align-items: center;
          padding: 0.2rem 0.55rem;
          border-radius: 999px;
          border: 1px solid rgba(39, 182, 255, 0.6);
          color: rgba(255,255,255,.92) !important;
          text-decoration: none;
          font-size: 0.62rem;
          text-transform: uppercase;
          letter-spacing: 0.12em;
          font-weight: 800;
        }
        .card-actions a:hover {
          background: rgba(39, 182, 255, 0.12);
        }
        .card-metrics {
          margin-top: 0.5rem;
          display: grid;
          grid-template-columns: repeat(5, minmax(0, 1fr));
          gap: 0.5rem;
          align-items: stretch;
        }
        .metric-box {
          background: rgba(8, 12, 18, 0.65);
          border: 1px solid rgba(39, 182, 255, 0.3);
          border-radius: 12px;
          padding: 0.55rem 0.7rem;
          min-height: 56px;
          display: flex;
          flex-direction: column;
          justify-content: center;
        }
        .metric-label {
          font-size: 0.58rem;
          text-transform: uppercase;
          letter-spacing: 0.12em;
          color: rgba(255,255,255,.65);
          margin-bottom: 0.14rem;
        }
        .metric-value {
          font-size: 1.18rem;
          font-weight: 800;
          color: rgba(255,255,255,.92);
          line-height: 1.05;
        }
        .metric-sub {
          font-size: 0.62rem;
          color: rgba(255, 255, 255, 0.6);
          margin-top: 0.2rem;
        }
        .metric-box.price-up {
          border-color: rgba(44, 255, 154, 0.8);
          background: rgba(44, 255, 154, 0.1);
        }
        .metric-box.price-up .metric-value {
          color: #2cff9a;
        }
        .metric-box.price-down {
          border-color: rgba(255, 179, 71, 0.75);
          background: rgba(255, 179, 71, 0.1);
        }
        .metric-box.price-down .metric-value {
          color: #ffb347;
        }
        .metric-box.price-flat {
          border-color: rgba(255, 255, 255, 0.14);
          background: rgba(255, 255, 255, 0.04);
        }
        .verdict-pill {
          border-radius: 999px;
          padding: 0.3rem 0.65rem;
          font-size: 0.64rem;
          text-transform: uppercase;
          letter-spacing: 0.14em;
          font-weight: 800;
          text-align: center;
          border: 1px solid;
        }
        .verdict-good-pill {
          background: rgba(44, 255, 154, 0.12);
          border-color: rgba(44, 255, 154, 0.85);
          color: #e9fff5;
          box-shadow: 0 0 12px rgba(44, 255, 154, 0.35);
        }
        .verdict-marginal-pill {
          background: rgba(255, 179, 71, 0.14);
          border-color: rgba(255, 179, 71, 0.8);
          color: #fff3e0;
          box-shadow: 0 0 12px rgba(255, 179, 71, 0.3);
        }
        .verdict-avoid-pill {
          background: rgba(255, 77, 77, 0.14);
          border-color: rgba(255, 77, 77, 0.85);
          color: #ffe9e9;
          box-shadow: 0 0 12px rgba(255, 77, 77, 0.32);
        }
        .top-buy-pill {
          background: rgba(57, 255, 152, 0.18);
          border-color: rgba(57, 255, 152, 0.9);
          color: #ecfff5;
          box-shadow: 0 0 14px rgba(57, 255, 152, 0.45);
        }
        .action-pill {
          background: rgba(39, 182, 255, 0.14);
          border-color: rgba(39, 182, 255, 0.85);
          color: #e4f7ff;
          box-shadow: 0 0 12px rgba(39, 182, 255, 0.28);
        }
        .support-pill {
          opacity: 0.82;
          font-size: 0.58rem;
          padding: 0.25rem 0.55rem;
        }
        .chip-row {
          margin-top: 0.3rem;
          display: flex;
          flex-wrap: wrap;
          gap: 0.3rem;
        }
        .confidence-badge-row {
          margin-top: 0.55rem;
          display: flex;
          flex-wrap: wrap;
          gap: 0.45rem;
        }
        .confidence-badge {
          display: inline-flex;
          align-items: center;
          gap: 0.45rem;
          padding: 0.32rem 0.58rem;
          border-radius: 999px;
          border: 1px solid rgba(39, 182, 255, 0.28);
          background: rgba(11, 15, 20, 0.72);
          font-size: 0.62rem;
        }
        .confidence-badge-label {
          letter-spacing: 0.1em;
          text-transform: uppercase;
          color: rgba(255, 255, 255, 0.6);
        }
        .confidence-badge-value {
          font-weight: 800;
          letter-spacing: 0.08em;
          color: rgba(255, 255, 255, 0.92);
        }
        .confidence-badge.badge-high {
          border-color: rgba(44, 255, 154, 0.5);
          background: rgba(44, 255, 154, 0.1);
        }
        .confidence-badge.badge-medium {
          border-color: rgba(255, 179, 71, 0.55);
          background: rgba(255, 179, 71, 0.1);
        }
        .confidence-badge.badge-low {
          border-color: rgba(255, 77, 77, 0.55);
          background: rgba(255, 77, 77, 0.1);
        }
        .confidence-badge.badge-neutral {
          border-color: rgba(39, 182, 255, 0.28);
          background: rgba(39, 182, 255, 0.08);
        }
        .chip.good {
          border-color: rgba(44, 255, 154, 0.65);
          background: rgba(44, 255, 154, 0.08);
        }
        .chip.warn {
          border-color: rgba(255, 179, 71, 0.7);
          background: rgba(255, 179, 71, 0.08);
        }
        .chip.danger {
          border-color: rgba(255, 77, 77, 0.6);
          background: rgba(255, 77, 77, 0.08);
        }
        @media (max-width: 900px) {
          .card-top {
            flex-direction: column;
            align-items: flex-start;
          }
          .vehicle-title {
            white-space: normal;
          }
          .card-metrics {
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
          }
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

allow_repairs = "general_condition" in sold_df.columns
tag_options = ["All"]
curves_df = load_curves()
allowed_tags = list_curve_tags(curves_df)
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
    curve_key = resolve_curve_canonical_tag(canonical_tag)
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

    curve_subset = curves_df[curves_df["canonical_tag"] == curve_key] if curve_key else pd.DataFrame()

    if not spec_reason:
        curve_estimate = interpolate_base_by_year(curve_subset, curve_key, year_val, odo_val)
        curve_base = curve_estimate
        curve_low = interpolate_curve_value(curve_subset, curve_key, year_val, odo_val, "price_low")
        curve_high = interpolate_curve_value(curve_subset, curve_key, year_val, odo_val, "price_high")
    if curve_estimate is None and not spec_reason:
        spec_reason = "NOT_COVERED"

    sold_price = row.get("price_numeric")
    delta = None
    delta_pct = None
    if curve_estimate is not None and sold_price is not None:
        delta = curve_estimate - sold_price
        if curve_estimate > 0:
            delta_pct = (delta / curve_estimate) * 100
    decision = compute_decision_metrics(
        row,
        curve_estimate,
        include_repairs=include_repairs,
    )
    max_bid = decision.get("max_bid")
    projected_profit_at_sold = decision.get("projected_profit_at_sold")
    profit_margin_pct = decision.get("profit_margin_pct")
    total_costs = decision.get("total_costs")
    platform_fees = decision.get("platform_fees")
    transport_costs = decision.get("transport")
    admin_costs = decision.get("admin_costs")
    risk_buffer = decision.get("risk_buffer")
    repair_cost = decision.get("repair_cost")
    net_delta = None
    if delta is not None:
        net_delta = delta - (repair_cost or 0)
    underbid_pct = compute_underbid_pct(sold_price, max_bid)

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
            "underbid_pct": underbid_pct,
            "projected_profit_at_sold": projected_profit_at_sold,
            "profit_margin_pct": profit_margin_pct,
            "total_costs": total_costs,
            "platform_fees": platform_fees,
            "transport_costs": transport_costs,
            "admin_costs": admin_costs,
            "risk_buffer": risk_buffer,
            "expected_auction_price": decision.get("expected_auction_price"),
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
if not results_df.empty:
    results_df["miss_classification"] = results_df.apply(classify_miss_reason, axis=1)
    results_df["date_sold_parsed"] = pd.to_datetime(results_df["date_sold"], errors="coerce")
    results_df["sold_month"] = results_df["date_sold_parsed"].dt.to_period("M").dt.to_timestamp()
    results_df = apply_global_sidebar_filters(
        results_df,
        state_columns=("location_state", "location", "yard"),
        vehicle_type_columns=("body_type", "body"),
        margin_columns=("profit_margin_pct", "delta_pct"),
        canonical_tag_column="canonical_tag",
        curve_tags=allowed_tags,
    )

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
true_miss_view = eligible_view[
    eligible_view["missed"] & (eligible_view["projected_profit_at_sold"].fillna(0) > 0)
].copy()
sold_count = int(view.shape[0])
with_curve = int(eligible_view.shape[0]) if not eligible_view.empty else 0
no_curve_count = int(no_curve_view.shape[0]) if not no_curve_view.empty else 0
total_missed = float(metric_series.clip(lower=0).sum()) if sold_count else 0.0
avg_missed = float(metric_series.clip(lower=0).mean()) if sold_count else 0.0
avg_missed_margin = (
    float(true_miss_view["profit_margin_pct"].dropna().mean())
    if not true_miss_view.empty and "profit_margin_pct" in true_miss_view.columns
    else None
)
largest_missed_deal = (
    float(true_miss_view["projected_profit_at_sold"].dropna().max())
    if not true_miss_view.empty and true_miss_view["projected_profit_at_sold"].notna().any()
    else None
)
avg_underbid_pct = (
    float(true_miss_view["underbid_pct"].dropna().mean())
    if not true_miss_view.empty and "underbid_pct" in true_miss_view.columns and true_miss_view["underbid_pct"].notna().any()
    else None
)
highest_theoretical_profit = (
    float(eligible_view["projected_profit_at_sold"].dropna().max())
    if not eligible_view.empty and "projected_profit_at_sold" in eligible_view.columns and eligible_view["projected_profit_at_sold"].notna().any()
    else None
)

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
<div class="kpi">
  <div class="k">Average Missed Margin</div>
  <div class="v">{pct(avg_missed_margin)}</div>
  <div class="s">True misses only</div>
</div>
<div class="kpi">
  <div class="k">Largest Missed Deal</div>
  <div class="v">{money(largest_missed_deal)}</div>
  <div class="s">Highest realised missed profit</div>
</div>
<div class="kpi">
  <div class="k">Average Underbid %</div>
  <div class="v">{pct(avg_underbid_pct)}</div>
  <div class="s">Gap between max bid and sold price</div>
</div>
<div class="kpi">
  <div class="k">Highest Theoretical Profit</div>
  <div class="v">{money(highest_theoretical_profit)}</div>
  <div class="s">Best profit signal in covered sold listings</div>
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

timeline_source = true_miss_view.copy()
if min_metric > 0:
    timeline_source = timeline_source[timeline_source["projected_profit_at_sold"].fillna(0) >= min_metric]

if not timeline_source.empty and "sold_month" in timeline_source.columns:
    timeline_df = (
        timeline_source.dropna(subset=["sold_month"])
        .assign(month_profit=lambda frame: frame["projected_profit_at_sold"].clip(lower=0))
        .groupby("sold_month", as_index=False)["month_profit"]
        .sum()
        .sort_values("sold_month")
    )
    if not timeline_df.empty:
        st.markdown('<div class="section-card" style="margin-top:14px;">', unsafe_allow_html=True)
        st.markdown("### Missed Profit Timeline")
        st.caption("True missed profit aggregated by sold month.")
        chart_df = timeline_df.rename(columns={"sold_month": "Month", "month_profit": "Missed Profit"})
        st.line_chart(chart_df.set_index("Month"))
        st.markdown("</div>", unsafe_allow_html=True)

classification_source = true_miss_view.copy()
if min_metric > 0:
    classification_source = classification_source[
        classification_source["projected_profit_at_sold"].fillna(0) >= min_metric
    ]
if not classification_source.empty and "miss_classification" in classification_source.columns:
    classification_df = (
        classification_source.assign(
            missed_profit=lambda frame: frame["projected_profit_at_sold"].clip(lower=0)
        )
        .groupby("miss_classification", as_index=False)
        .agg(
            listings=("url", "count"),
            missed_profit=("missed_profit", "sum"),
            avg_profit=("missed_profit", "mean"),
        )
        .sort_values(["missed_profit", "listings"], ascending=[False, False])
    )
    if not classification_df.empty:
        st.markdown('<div class="section-card" style="margin-top:14px;">', unsafe_allow_html=True)
        st.markdown("### Miss Classification")
        st.caption("Heuristic buckets to explain why opportunities were missed.")
        summary_chips = "".join(
            f'<div class="chip">{html.escape(str(row["miss_classification"]))}: '
            f'{int(row["listings"]):,} listings / {money(row["missed_profit"])}</div>'
            for _, row in classification_df.iterrows()
        )
        st.markdown(f'<div class="pattern">{summary_chips}</div>', unsafe_allow_html=True)
        display_df = classification_df.rename(
            columns={
                "miss_classification": "classification",
                "missed_profit": "missed_profit_total",
                "avg_profit": "average_profit",
            }
        ).copy()
        display_df["missed_profit_total"] = display_df["missed_profit_total"].apply(money)
        display_df["average_profit"] = display_df["average_profit"].apply(money)
        st.dataframe(display_df, width="stretch", hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

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
    avg_label = "avg profit" if only_missed else "avg delta"
    group_summary = f"{money(group_avg)} {avg_label} | {len(group_df):,} listings"
    st.markdown(
        f'<div class="group-header">{html.escape(group)} <span>{group_summary}</span></div>',
        unsafe_allow_html=True,
    )

    group_df = group_df.sort_values(metric_field, ascending=False, na_position="last")
    for _, row in group_df.iterrows():
        render_sold_analysis_card(
            row,
            only_missed=only_missed,
            include_repairs=include_repairs,
            metric_field=metric_field,
            top_threshold=top_threshold,
            low_threshold=low_threshold,
        )


st.markdown("</div>", unsafe_allow_html=True)
