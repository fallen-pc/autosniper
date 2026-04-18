from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from shared.calibration import (
    build_calibration_detail,
    load_calibration_inputs,
    summarize_calibration,
)
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Valuation Calibration", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "VALUATION CALIBRATION",
    "Back-test current max-bid and profit rules against restricted sold outcomes.",
    show_logo=False,
)


def _format_money(value: object) -> str:
    try:
        if value is None or pd.isna(value):
            return "N/A"
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "N/A"


def _format_pct(value: object) -> str:
    try:
        if value is None or pd.isna(value):
            return "N/A"
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def _safe_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


@st.cache_data(ttl=300)
def _load_calibration(include_repairs: bool, limit: int | None) -> pd.DataFrame:
    sold_df, group_map_df, curves_df = load_calibration_inputs()
    return build_calibration_detail(
        sold_df,
        group_map_df,
        curves_df,
        include_repairs=include_repairs,
        limit=limit,
    )


st.markdown(
    clean_html(
        """
        <style>
        .calibration-card {
            background: linear-gradient(145deg, rgba(18, 27, 42, 0.98), rgba(7, 11, 18, 0.98));
            border: 1px solid rgba(42, 176, 255, 0.18);
            border-radius: 18px;
            padding: 1rem;
            min-height: 100%;
            box-shadow: 0 18px 36px rgba(2, 8, 18, 0.26);
        }
        .calibration-card .label {
            color: var(--autosniper-muted);
            font-size: 0.75rem;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }
        .calibration-card .value {
            color: var(--autosniper-primary);
            font-size: 1.8rem;
            font-weight: 800;
            margin-top: 0.35rem;
        }
        .calibration-card .note {
            color: var(--autosniper-muted);
            font-size: 0.85rem;
            margin-top: 0.25rem;
        }
        .calibration-warning {
            border-left: 4px solid #f7b955;
            padding: 0.8rem 1rem;
            background: rgba(247, 185, 85, 0.08);
            border-radius: 12px;
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

control_a, control_b, control_c = st.columns([1, 1, 2])
with control_a:
    include_repairs = st.checkbox("Include repair/risk costs", value=True)
with control_b:
    fast_sample = st.checkbox("Fast sample only", value=False)
with control_c:
    st.caption(
        "This page is read-only. It does not change bidding rules; it shows what the current rules would have done on past sold rows."
    )

limit = 50 if fast_sample else None
detail_df = _load_calibration(include_repairs, limit)

if detail_df.empty:
    st.warning("No calibration rows are available. Build restricted sold data and curves first.")
    st.stop()

summary = summarize_calibration(detail_df)

summary_cols = st.columns(5)
summary_cards = [
    ("Rows checked", f"{summary['total_rows']:,}", "Restricted sold rows"),
    ("Curve covered", f"{summary['covered_rows']:,}", "Rows with usable curve"),
    ("Profitable wins", f"{summary['profitable_within_bid_rows']:,}", "Inside current max bid"),
    ("Overbid risk", f"{summary['overbid_risk_rows']:,}", "Would win but lose money"),
    ("Priced out", f"{summary['priced_out_profitable_rows']:,}", "Profitable but max bid too low"),
]
for column, (label, value, note) in zip(summary_cols, summary_cards):
    column.markdown(
        clean_html(
            f"""
            <div class="calibration-card">
                <div class="label">{label}</div>
                <div class="value">{value}</div>
                <div class="note">{note}</div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )

profit_cols = st.columns(2)
profit_cols[0].metric(
    "Total theoretical profit inside max bid",
    _format_money(summary.get("total_profitable_within_bid")),
)
profit_cols[1].metric(
    "Average profit inside max bid",
    _format_money(summary.get("avg_profit_within_bid")),
)

if int(summary.get("overbid_risk_rows") or 0) == 0:
    st.markdown(
        '<div class="calibration-warning">Current calibration shows no overbid-loss rows in the checked restricted sold set. That is good, but the priced-out count should be reviewed before loosening buffers.</div>',
        unsafe_allow_html=True,
    )
else:
    st.error("Overbid-risk rows exist. Review them before loosening any buying rules.")

section_heading("Filters", "Inspect the calibration evidence by reason, make, model, or curve.")
filter_a, filter_b, filter_c, filter_d = st.columns(4)
reason_options = sorted(detail_df["calibration_reason"].dropna().astype(str).unique().tolist())
reason_filter = filter_a.multiselect("Reason", reason_options, default=reason_options)
make_options = sorted(detail_df["make"].dropna().astype(str).unique().tolist()) if "make" in detail_df else []
make_filter = filter_b.multiselect("Make", make_options)
model_options = sorted(detail_df["model"].dropna().astype(str).unique().tolist()) if "model" in detail_df else []
model_filter = filter_c.multiselect("Model", model_options)
tag_options = sorted(detail_df["canonical_tag"].dropna().astype(str).unique().tolist())
tag_filter = filter_d.multiselect("Curve", tag_options)

view_df = detail_df.copy()
if reason_filter:
    view_df = view_df[view_df["calibration_reason"].isin(reason_filter)]
if make_filter:
    view_df = view_df[view_df["make"].astype(str).isin(make_filter)]
if model_filter:
    view_df = view_df[view_df["model"].astype(str).isin(model_filter)]
if tag_filter:
    view_df = view_df[view_df["canonical_tag"].astype(str).isin(tag_filter)]

tab_summary, tab_priced_out, tab_risk, tab_all = st.tabs(
    ["Reason Summary", "Priced-Out Winners", "Overbid Risk", "All Rows"]
)

with tab_summary:
    section_heading("Reason Summary", "What the current rules would have done historically.")
    reason_summary = (
        view_df.groupby("calibration_reason", dropna=False)
        .agg(
            rows=("url", "count"),
            avg_profit=("projected_profit_at_sold", "mean"),
            total_positive_profit=("projected_profit_at_sold", lambda s: float(s.dropna().clip(lower=0).sum())),
            avg_bid_gap=("bid_gap", "mean"),
        )
        .reset_index()
        .sort_values(["rows", "total_positive_profit"], ascending=[False, False])
    )
    reason_summary["avg_profit"] = reason_summary["avg_profit"].map(_format_money)
    reason_summary["total_positive_profit"] = reason_summary["total_positive_profit"].map(_format_money)
    reason_summary["avg_bid_gap"] = reason_summary["avg_bid_gap"].map(_format_money)
    st.dataframe(reason_summary, use_container_width=True, hide_index=True)

with tab_priced_out:
    section_heading(
        "Priced-Out Winners",
        "Rows that look profitable at sold price, but the current max-bid rule would have stopped bidding.",
    )
    priced_out_reasons = {"curve too conservative", "bid cap too conservative", "risk deduction too large"}
    priced_out = view_df[view_df["calibration_reason"].isin(priced_out_reasons)].copy()
    priced_out = priced_out.sort_values("projected_profit_at_sold", ascending=False, na_position="last")
    display_cols = [
        "year",
        "make",
        "model",
        "variant",
        "sold_price",
        "max_bid",
        "bid_gap",
        "projected_profit_at_sold",
        "delta_pct",
        "repair_cost_estimate",
        "risk_buffer",
        "calibration_reason",
        "url",
    ]
    priced_display = priced_out[[col for col in display_cols if col in priced_out.columns]].copy()
    for money_col in ("sold_price", "max_bid", "bid_gap", "projected_profit_at_sold", "repair_cost_estimate", "risk_buffer"):
        if money_col in priced_display:
            priced_display[money_col] = priced_display[money_col].map(_format_money)
    if "delta_pct" in priced_display:
        priced_display["delta_pct"] = priced_display["delta_pct"].map(_format_pct)
    st.dataframe(
        priced_display,
        use_container_width=True,
        hide_index=True,
        column_config={"url": st.column_config.LinkColumn("Listing", display_text="Open")},
    )

with tab_risk:
    section_heading("Overbid Risk", "Rows the rules would have won but with non-positive projected profit.")
    risk_df = view_df[view_df["calibration_reason"] == "overbid risk"].copy()
    if risk_df.empty:
        st.success("No overbid-risk rows in the current filtered view.")
    else:
        risk_df = risk_df.sort_values("projected_profit_at_sold", ascending=True, na_position="last")
        risk_display = risk_df[[col for col in display_cols if col in risk_df.columns]].copy()
        for money_col in ("sold_price", "max_bid", "bid_gap", "projected_profit_at_sold", "repair_cost_estimate", "risk_buffer"):
            if money_col in risk_display:
                risk_display[money_col] = risk_display[money_col].map(_format_money)
        if "delta_pct" in risk_display:
            risk_display["delta_pct"] = risk_display["delta_pct"].map(_format_pct)
        st.dataframe(
            risk_display,
            use_container_width=True,
            hide_index=True,
            column_config={"url": st.column_config.LinkColumn("Listing", display_text="Open")},
        )

with tab_all:
    section_heading("All Calibration Rows", "Download or inspect the full filtered evidence table.")
    all_display = view_df.copy()
    st.download_button(
        "Download filtered CSV",
        data=all_display.to_csv(index=False).encode("utf-8"),
        file_name="valuation_calibration_filtered.csv",
        mime="text/csv",
    )
    compact_cols = [
        "year",
        "make",
        "model",
        "variant",
        "canonical_tag",
        "sold_price",
        "curve_estimate",
        "max_bid",
        "projected_profit_at_sold",
        "calibration_reason",
        "url",
    ]
    compact = all_display[[col for col in compact_cols if col in all_display.columns]].copy()
    for money_col in ("sold_price", "curve_estimate", "max_bid", "projected_profit_at_sold"):
        if money_col in compact:
            compact[money_col] = compact[money_col].map(_format_money)
    st.dataframe(
        compact,
        use_container_width=True,
        hide_index=True,
        column_config={"url": st.column_config.LinkColumn("Listing", display_text="Open")},
    )

section_heading("Report Files", "The script can also write CSV and Markdown outputs.")
st.code(r".\venv\Scripts\python.exe scripts\calibration_report.py", language="powershell")
summary_path = Path("output/calibration/valuation_calibration_summary.md")
detail_path = Path("output/calibration/valuation_calibration_detail.csv")
st.caption(
    f"Latest script output paths: `{summary_path}` and `{detail_path}`. These output files are runtime artifacts and are not committed by default."
)
