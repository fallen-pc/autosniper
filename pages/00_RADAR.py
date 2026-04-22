import pandas as pd
import streamlit as st

from shared.global_filters import apply_global_sidebar_filters, render_global_sidebar_filters
from shared.ops_utils import (
    apply_global_filters,
    build_curve_meta,
    build_issue_index,
    confidence_bucket,
    load_active_df,
    load_curves_df,
    load_flags_df,
    load_static_df,
    load_valuations_df,
    parse_currency,
    parse_percent,
    parse_time_remaining_hours,
    time_bucket,
)
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro, section_heading
from shared.valuation_display import conservative_margin_percent, is_safe_opportunity_row


st.set_page_config(page_title="Radar", layout="wide")
render_global_sidebar_filters()
inject_global_styles()
display_banner()
page_intro("RADAR", "Live trading console ranked by profit potential.", show_logo=False)


def _safe_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _build_profit_value(row: pd.Series) -> float | None:
    for key in ("net_profit_worst", "net_profit_mid", "expected_profit"):
        value = parse_currency(row.get(key))
        if value is not None:
            return value
    resale_mid = parse_currency(row.get("resale_mid"))
    current_bid = parse_currency(row.get("price"))
    if resale_mid is not None and current_bid is not None:
        return resale_mid - current_bid
    return None


def _risk_level(row: pd.Series) -> str:
    if bool(row.get("is_flagged")) or not bool(row.get("has_curve")):
        return "High"
    if str(row.get("severity", "")).lower() in {"red", "yellow"}:
        return "High"
    if float(row.get("issue_count") or 0) >= 2:
        return "Medium"
    if str(row.get("confidence_bucket", "")).lower() == "low":
        return "Medium"
    return "Low"


def _radar_signals(row: pd.Series) -> str:
    signals: list[str] = []
    profit_value = parse_currency(row.get("profit_value"))
    margin_value = conservative_margin_percent(row)
    time_hours = row.get("time_remaining_hours")
    risk_level = _risk_level(row)
    if (profit_value is not None and profit_value >= 5000) or (margin_value is not None and margin_value >= 20):
        signals.append("🔥")
    if risk_level in {"High", "Medium"}:
        signals.append("⚠")
    if time_hours is not None and float(time_hours) <= 24:
        signals.append("⏳")
    return " ".join(signals) if signals else "·"


def _vehicle_label(row: pd.Series) -> str:
    parts = [
        _safe_text(row.get("year")),
        _safe_text(row.get("make")),
        _safe_text(row.get("model")),
        _safe_text(row.get("variant")),
    ]
    return " ".join(part for part in parts if part) or "Listing"


st.markdown(
    clean_html(
        """
        <style>
        .radar-summary-card {
            background: linear-gradient(145deg, rgba(26, 33, 48, 0.98), rgba(10, 16, 28, 0.98));
            border: 1px solid rgba(31, 166, 255, 0.16);
            border-radius: 16px;
            padding: 1rem;
            box-shadow: 0 16px 30px rgba(4, 9, 17, 0.28);
        }
        .radar-summary-card .label {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: var(--autosniper-muted);
        }
        .radar-summary-card .value {
            margin-top: 0.35rem;
            font-size: 1.8rem;
            font-weight: 800;
            color: var(--autosniper-primary);
        }
        .radar-summary-card .note {
            margin-top: 0.25rem;
            font-size: 0.85rem;
            color: var(--autosniper-muted);
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

static_df = load_static_df()
active_df = load_active_df()
valuations_df = load_valuations_df()

if active_df.empty:
    st.warning("No active listings available. Run the scrapers to populate active_vehicle_details.csv.")
    st.stop()

curves_df = load_curves_df()
curve_meta = build_curve_meta(curves_df)
issue_df = build_issue_index(static_df, active_df, valuations_df, curve_meta=curve_meta)

radar_df = active_df.merge(issue_df, on="url", how="left")
if not valuations_df.empty:
    radar_df = radar_df.merge(valuations_df, on="url", how="left", suffixes=("", "_ai"))

if "confidence" not in radar_df.columns:
    radar_df["confidence"] = None
if "verdict" not in radar_df.columns and "computed_verdict" in radar_df.columns:
    radar_df["verdict"] = radar_df["computed_verdict"]

radar_df["time_remaining_hours"] = radar_df["time_remaining_or_date_sold"].apply(parse_time_remaining_hours)
radar_df["time_bucket"] = radar_df["time_remaining_hours"].apply(time_bucket)
radar_df["confidence_bucket"] = radar_df["confidence"].apply(confidence_bucket)
radar_df["has_curve"] = radar_df["canonical_tag"].apply(lambda tag: bool(tag) and str(tag).strip() in curve_meta)
radar_df["profit_margin_value"] = radar_df.apply(conservative_margin_percent, axis=1)
radar_df["recommended_max_bid_value"] = radar_df.get("recommended_max_bid", pd.Series(dtype=float)).apply(parse_currency)
radar_df["resale_mid_value"] = radar_df.get("resale_mid", pd.Series(dtype=float)).apply(parse_currency)
radar_df["current_bid_value"] = radar_df.get("price", pd.Series(dtype=float)).apply(parse_currency)
radar_df["profit_value"] = radar_df.apply(_build_profit_value, axis=1)
radar_df["is_tradeable"] = radar_df.apply(is_safe_opportunity_row, axis=1)
radar_df["severity"] = radar_df["severity"].fillna("green")
radar_df["issue_summary"] = radar_df["issue_summary"].fillna("")
radar_df["issue_codes"] = radar_df["issue_codes"].apply(
    lambda codes: " ".join(f"[{code}]" for code in codes) if isinstance(codes, list) else ""
)

flags_df = load_flags_df()
flag_lookup = {}
if not flags_df.empty and "url" in flags_df.columns:
    flags_df["timestamp"] = pd.to_datetime(flags_df.get("timestamp"), errors="coerce")
    latest_flags = flags_df.sort_values("timestamp").drop_duplicates("url", keep="last")
    flag_lookup = latest_flags.set_index("url").to_dict(orient="index")

radar_df["flag"] = radar_df["url"].map(lambda url: flag_lookup.get(url, {}).get("flag", ""))
radar_df["flag_reason"] = radar_df["url"].map(lambda url: flag_lookup.get(url, {}).get("reason", ""))
radar_df["is_flagged"] = radar_df["flag"].astype(str).str.strip().ne("")
radar_df["risk_level"] = radar_df.apply(_risk_level, axis=1)
radar_df["signals"] = radar_df.apply(_radar_signals, axis=1)
radar_df["vehicle"] = radar_df.apply(_vehicle_label, axis=1)

radar_df = apply_global_sidebar_filters(
    radar_df,
    state_columns=("location_state", "rego_state", "location"),
    vehicle_type_columns=("body_type", "body"),
    margin_columns=("profit_margin_value", "profit_margin_percent"),
    canonical_tag_column="canonical_tag",
    curve_tags=curve_meta.keys(),
)

section_heading("Radar Controls", "Live auction controls layered on top of the global sidebar filters.")
control_a, control_b, control_c, control_d = st.columns(4)
make_filter = control_a.multiselect(
    "Make",
    sorted(radar_df["make"].dropna().astype(str).unique().tolist()) if "make" in radar_df.columns else [],
)
verdict_filter = control_b.multiselect(
    "Verdict",
    sorted(radar_df["verdict"].dropna().astype(str).unique().tolist()) if "verdict" in radar_df.columns else [],
)
time_filter = control_c.multiselect(
    "Time Bucket",
    ["<24h", "1-2d", "2-3d", "3+d", "Unknown"],
    default=["<24h", "1-2d", "2-3d", "3+d", "Unknown"],
)
confidence_filter = control_d.multiselect(
    "Confidence",
    ["High", "Medium", "Low", "Unknown"],
    default=["High", "Medium", "Low", "Unknown"],
)
toggle_a, toggle_b, toggle_c = st.columns(3)
hide_flagged = toggle_a.checkbox("Hide flagged", value=False)
only_high_value = toggle_b.checkbox("Only high value", value=False)
ending_soon_only = toggle_c.checkbox("Ending within 24h", value=False)

filtered_df = apply_global_filters(
    radar_df,
    make_filter=make_filter,
    verdict_filter=verdict_filter,
    confidence_filter=confidence_filter,
    time_bucket_filter=time_filter,
)
if hide_flagged:
    filtered_df = filtered_df[~filtered_df["is_flagged"]]
if only_high_value:
    filtered_df = filtered_df[
        filtered_df["is_tradeable"]
        & (
            (filtered_df["profit_value"].fillna(0) >= 5000)
            | (filtered_df["profit_margin_value"].fillna(0) >= 20)
        )
    ]
if ending_soon_only:
    filtered_df = filtered_df[filtered_df["time_remaining_hours"].fillna(9999) <= 24]

filtered_df["ranking_score"] = (
    filtered_df["profit_value"].fillna(0)
    + filtered_df["profit_margin_value"].fillna(0) * 45
    + filtered_df["confidence"].fillna(0) * 800
    - filtered_df["issue_count"].fillna(0) * 400
    - (~filtered_df["is_tradeable"]).astype(int) * 1_000_000
)
filtered_df = filtered_df.sort_values(
    by=["ranking_score", "profit_value", "confidence", "time_remaining_hours"],
    ascending=[False, False, False, True],
    na_position="last",
)

summary_cols = st.columns(4)
summary_cards = [
    ("Visible auctions", f"{len(filtered_df):,}", "After global + radar filters"),
    ("High value", f"{int((filtered_df['signals'].astype(str).str.contains('🔥')).sum()):,}", "Profit-led opportunities"),
    ("Risk flagged", f"{int((filtered_df['signals'].astype(str).str.contains('⚠')).sum()):,}", "Needs caution"),
    ("Ending soon", f"{int((filtered_df['signals'].astype(str).str.contains('⏳')).sum()):,}", "Within 24 hours"),
]
for column, (label, value, note) in zip(summary_cols, summary_cards):
    column.markdown(
        clean_html(
            f"""
            <div class="radar-summary-card">
                <div class="label">{label}</div>
                <div class="value">{value}</div>
                <div class="note">{note}</div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )

left, right = st.columns([3.2, 1.8], gap="large")

with left:
    section_heading("Trading Screen", "Live auctions ranked by profit potential.")
    table_df = filtered_df.copy()
    table_df["Current Bid"] = table_df["current_bid_value"].map(lambda value: f"${value:,.0f}" if pd.notna(value) else "N/A")
    table_df["Max Bid"] = table_df["recommended_max_bid_value"].map(lambda value: f"${value:,.0f}" if pd.notna(value) else "N/A")
    table_df["Profit"] = table_df["profit_value"].map(lambda value: f"${value:,.0f}" if pd.notna(value) else "N/A")
    table_df["Confidence"] = table_df["confidence_bucket"].fillna("Unknown")
    table_df["Time Remaining"] = table_df["time_remaining_or_date_sold"].fillna("Unknown")
    table_df["Margin"] = table_df["profit_margin_value"].map(lambda value: f"{value:.1f}%" if pd.notna(value) else "N/A")
    table_df["Listing"] = table_df["url"]

    display_cols = [
        "signals",
        "vehicle",
        "Current Bid",
        "Max Bid",
        "Profit",
        "Confidence",
        "Time Remaining",
        "Margin",
        "location",
        "Listing",
    ]
    available_cols = [column for column in display_cols if column in table_df.columns]
    radar_table = table_df[available_cols].copy()
    radar_table.insert(0, "Select", False)

    edited = st.data_editor(
        radar_table,
        hide_index=True,
        width="stretch",
        disabled=[column for column in radar_table.columns if column != "Select"],
        column_config={
            "Select": st.column_config.CheckboxColumn("Select"),
            "Listing": st.column_config.LinkColumn("Listing", display_text="Open"),
        },
        key="radar_table_editor",
    )
    selected_rows = edited[edited["Select"]]
    if len(selected_rows) == 1:
        selected_url = selected_rows.iloc[0].get("Listing")
        selected_match = filtered_df[filtered_df["url"] == selected_url]
        if not selected_match.empty:
            st.session_state["ops_selected_url"] = selected_match.iloc[0]["url"]
    elif len(selected_rows) > 1:
        st.info("Select one auction at a time to inspect it on the right.")

with right:
    section_heading("Inspect Opportunity", "Use this panel to validate the trade before switching pages.")
    selected_url = st.session_state.get("ops_selected_url")
    if not selected_url:
        st.info("Select a row on the trading screen to inspect it.")
    else:
        selected_row = filtered_df[filtered_df["url"] == selected_url]
        if selected_row.empty:
            st.warning("Selected listing is no longer visible under the current filters.")
        else:
            row = selected_row.iloc[0]
            st.markdown(f"**{row.get('vehicle', 'Listing')}**")
            st.caption(_safe_text(row.get("url")))
            st.metric("Signals", _safe_text(row.get("signals")) or "·")
            st.metric("Risk Level", _safe_text(row.get("risk_level")) or "Unknown")
            st.metric("Confidence", _safe_text(row.get("confidence_bucket")) or "Unknown")
            st.metric("Current Bid", f"${row['current_bid_value']:,.0f}" if pd.notna(row.get("current_bid_value")) else "N/A")
            st.metric("Max Bid", f"${row['recommended_max_bid_value']:,.0f}" if pd.notna(row.get("recommended_max_bid_value")) else "N/A")
            st.metric("Profit", f"${row['profit_value']:,.0f}" if pd.notna(row.get("profit_value")) else "N/A")
            st.markdown("**Issue Summary**")
            st.write(_safe_text(row.get("issue_summary")) or "No issues surfaced.")
            if row.get("url"):
                link_button = getattr(st, "link_button", None)
                if callable(link_button):
                    link_button("Open listing", row.get("url"))
                else:
                    st.markdown(f"[Open listing]({row.get('url')})")
            if st.button("Open detail view", key="radar_open_detail"):
                try:
                    st.switch_page("pages/02_DETAIL.py")
                except Exception:
                    st.info("Open the Detail page from the sidebar to view this listing.")
            if st.button("Open AI analysis", key="radar_open_ai"):
                st.session_state["ai_focus_url"] = row.get("url")
                try:
                    st.switch_page("pages/6_AI_ANALYSIS.py")
                except Exception:
                    st.info("Open AI Analysis from the sidebar to inspect this listing.")
