from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from shared.calibration import build_calibration_detail, load_calibration_inputs, summarize_calibration
from shared.data_loader import dataset_path
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Model Proof", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "MODEL PROOF",
    "Current evidence for profit selection, separated by real and simulated outcomes.",
    show_logo=False,
)

SIMULATED_METRICS_PATH = Path("output") / "eval" / "simulated_verdict_proxy" / "buy_selection_classification.csv"
SIMULATED_JOIN_PATH = Path("output") / "eval" / "simulated_verdict_proxy" / "buy_selection_join.csv"
SIMULATED_OUTCOMES_PATH = dataset_path("simulated_sold_outcomes.csv")
REAL_OUTCOMES_PATH = dataset_path("scored_listings_enriched.csv")
RETAIL_MEDIAN_OUTCOMES_PATH = dataset_path("model_audit/simulated_retail_median_outcomes.csv")
RETAIL_MEDIAN_METRICS_PATH = Path("output") / "eval" / "simulated_retail_median" / "buy_selection_classification.csv"


@st.cache_data(ttl=300)
def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not read {path}: {exc}")
        return pd.DataFrame()


def format_ratio(value: object) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value) * 100:.1f}%"


def format_int(value: object) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{int(float(value)):,}"


def format_money(value: object) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"${float(value):,.0f}"


def metric_value(metrics: pd.Series, column: str) -> object:
    return metrics[column] if column in metrics.index else pd.NA


def prediction_count_label(metrics: pd.Series) -> str:
    source = str(metric_value(metrics, "prediction_source")).strip()
    if source == "computed_verdict":
        return "Buyable verdicts"
    if source == "action":
        return "Buy actions"
    return "Positive predictions"


def numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


@st.cache_data(ttl=300)
def load_calibration(include_repairs: bool, limit: int | None) -> pd.DataFrame:
    sold_df, group_map_df, curves_df = load_calibration_inputs()
    return build_calibration_detail(
        sold_df,
        group_map_df,
        curves_df,
        include_repairs=include_repairs,
        limit=limit,
    )


def render_status_badge(label: str, tone: str) -> None:
    palette = {
        "ok": ("var(--autosniper-success)", "rgba(94, 230, 167, 0.12)"),
        "warn": ("var(--autosniper-warning)", "rgba(255, 167, 38, 0.12)"),
        "info": ("var(--autosniper-accent)", "rgba(31, 166, 255, 0.12)"),
    }
    text_color, bg_color = palette.get(tone, palette["info"])
    st.markdown(
        f"""
        <div style="
            display:inline-block;
            padding:0.34rem 0.58rem;
            border-radius:8px;
            background:{bg_color};
            color:{text_color};
            font-weight:700;
            font-size:0.86rem;
        ">{label}</div>
        """,
        unsafe_allow_html=True,
    )


sim_metrics_df = load_csv(SIMULATED_METRICS_PATH)
sim_join_df = load_csv(SIMULATED_JOIN_PATH)
sim_outcomes_df = load_csv(SIMULATED_OUTCOMES_PATH)
real_df = load_csv(REAL_OUTCOMES_PATH)

real_profit = numeric_series(real_df, "actual_profit")
real_rows = int(real_profit.notna().sum())

section_heading("Proof Level", "Real outcomes and proxy outcomes are intentionally separate.")
status_cols = st.columns(2)
with status_cols[0]:
    st.subheader("Real settled-profit benchmark")
    if real_rows:
        render_status_badge("Available", "ok")
        st.metric("Rows with actual profit", format_int(real_rows))
    else:
        render_status_badge("Unavailable", "warn")
        st.metric("Rows with actual profit", "0")
        st.caption("No real post-purchase resale outcomes exist yet, so this page does not claim real settled-profit proof.")

with status_cols[1]:
    st.subheader("Simulated profit benchmark")
    if sim_metrics_df.empty:
        render_status_badge("Not generated", "warn")
        st.caption(
            "Run `scripts/generate_simulated_sold_outcomes.py`, then `scripts/evaluate_buy_selection.py "
            "--benchmark-type simulated --profit-column simulated_actual_profit --prediction-source computed_verdict`."
        )
    else:
        render_status_badge("Available", "ok")
        st.caption("Proxy evidence only: simulated sale prices come from resale estimate fields, not real sales.")

if not sim_metrics_df.empty:
    metrics = sim_metrics_df.iloc[0]

    section_heading("Simulated Verdict-Proxy Result", "Buyable verdicts tested against simulated profit.")
    metric_cols = st.columns(6)
    metric_cols[0].metric("Rows tested", format_int(metric_value(metrics, "rows")))
    metric_cols[1].metric(prediction_count_label(metrics), format_int(metric_value(metrics, "buy_predictions")))
    metric_cols[2].metric("Simulated profitable", format_int(metric_value(metrics, "profitable_actuals")))
    metric_cols[3].metric("Precision", format_ratio(metric_value(metrics, "precision")))
    metric_cols[4].metric("Recall", format_ratio(metric_value(metrics, "recall")))
    metric_cols[5].metric("F1", format_ratio(metric_value(metrics, "f1")))

    st.info(
        "Interpretation: under simulated resale assumptions, every buyable-verdict pick was profitable "
        "in the current dataset, but the system caught only a small share of all simulated-profitable rows."
    )

    with st.expander("What these metrics mean", expanded=True):
        st.markdown(
            """
            - **Precision**: of the rows the system marked buyable, how many were profitable under the simulation.
            - **Recall**: of all rows that were profitable under the simulation, how many the system caught.
            - **F1**: one combined score balancing precision and recall.
            - **Current shape**: high precision and low recall means the system is conservative.
            """
        )

    section_heading("Benchmark Contract", "The labels on this page are part of the evidence.")
    contract_cols = st.columns(3)
    contract_cols[0].metric("Benchmark type", str(metric_value(metrics, "benchmark_type")))
    contract_cols[1].metric("Prediction source", str(metric_value(metrics, "prediction_source")))
    contract_cols[2].metric("Profit column", str(metric_value(metrics, "profit_column")))
    st.caption(f"Positive labels: {metric_value(metrics, 'positive_labels')}")

    if not sim_outcomes_df.empty:
        profit = numeric_series(sim_outcomes_df, "simulated_actual_profit")
        source_counts = (
            sim_outcomes_df.get("simulated_source", pd.Series(dtype=object))
            .fillna("")
            .astype(str)
            .str.strip()
            .replace("", "missing")
            .value_counts()
            .rename_axis("simulated_source")
            .reset_index(name="rows")
        )
        section_heading("Simulated Outcome Inputs", "Where the proxy sale prices came from.")
        input_cols = st.columns(4)
        input_cols[0].metric("Outcome rows", format_int(len(sim_outcomes_df)))
        input_cols[1].metric("Rows with simulated profit", format_int(profit.notna().sum()))
        input_cols[2].metric("Profitable rows", format_int((profit > 0).sum()))
        input_cols[3].metric("Average simulated profit", format_money(profit.mean()))
        st.dataframe(source_counts, width="stretch", hide_index=True)

    section_heading("Rows Behind The Result", "Inspect the joined proof data.")
    if sim_join_df.empty:
        st.info("No joined simulated benchmark rows were written.")
    else:
        view_df = sim_join_df.copy()
        verdicts = sorted(
            value
            for value in view_df.get("computed_verdict", pd.Series(dtype=object)).dropna().astype(str).unique()
            if value.strip()
        )
        selected_verdict = st.selectbox("Computed verdict", ["All"] + verdicts, index=0)
        if selected_verdict != "All":
            view_df = view_df[view_df["computed_verdict"].astype(str) == selected_verdict]

        only_selected = st.checkbox("Only buyable-verdict predictions", value=False)
        if only_selected and "y_pred_buy" in view_df.columns:
            view_df = view_df[view_df["y_pred_buy"].astype(bool)]

        display_columns = [
            "computed_verdict",
            "prediction_label",
            "simulated_sale_price",
            "simulated_actual_profit",
            "simulated_source",
            "purchase_price",
            "y_pred_buy",
            "y_true_profitable",
            "url",
        ]
        display_columns = [column for column in display_columns if column in view_df.columns]
        st.dataframe(view_df[display_columns].head(250), width="stretch", hide_index=True)
else:
    render_status_badge("Not generated", "warn")
    st.caption(
        "Run `scripts/generate_simulated_sold_outcomes.py`, then `scripts/evaluate_buy_selection.py "
        "--benchmark-type simulated --profit-column simulated_actual_profit --prediction-source computed_verdict`."
    )

retail_outcomes_df = load_csv(RETAIL_MEDIAN_OUTCOMES_PATH)
retail_metrics_df = load_csv(RETAIL_MEDIAN_METRICS_PATH)

section_heading(
    "Retail-Median Proxy Benchmark",
    "Independent of curve estimates: uses current Autotrader/Carsales asking prices for the same spec as a resale proxy.",
)
if retail_outcomes_df.empty:
    st.info(
        "Run `scripts/generate_retail_median_outcomes.py`, then `scripts/evaluate_buy_selection.py "
        "--scored CSV_data/model_audit/simulated_retail_median_outcomes.csv "
        "--profit-column simulated_profit --benchmark-type simulated "
        "--out-dir output/eval/simulated_retail_median`."
    )
else:
    st.caption(
        "Proxy evidence only: resale price = median of several concurrent Autotrader/Carsales listings "
        "for the same make/model/variant family/body/fuel/transmission, matched within a year and odometer "
        "tolerance. Rows are dropped, not guessed at, when fewer than 5 matches exist. No real sale has "
        "occurred yet."
    )
    retail_profit = numeric_series(retail_outcomes_df, "simulated_profit")
    has_profit = retail_outcomes_df[retail_profit.notna()]
    retail_cols = st.columns(4)
    retail_cols[0].metric("Rows scored", format_int(len(retail_outcomes_df)))
    retail_cols[1].metric("Rows with retail match", format_int(retail_profit.notna().sum()))
    retail_cols[2].metric("Simulated profitable", format_int((retail_profit > 0).sum()))
    retail_cols[3].metric("Median simulated profit", format_money(retail_profit.median()))

    if not has_profit.empty:
        by_action = has_profit.copy()
        action_labels = (
            by_action["action_label_display"]
            if "action_label_display" in by_action.columns
            else by_action["resolved_action_label"]
            if "resolved_action_label" in by_action.columns
            else by_action["action_label"]
            if "action_label" in by_action.columns
            else pd.Series("", index=by_action.index)
        )
        by_action["action_label_display"] = action_labels.fillna("").astype(str).str.strip().replace("", "Missing action label")
        by_verdict = (
            by_action.groupby("action_label_display")["simulated_profit"]
            .agg(["count", "median", "mean"])
            .rename(columns={"count": "rows", "median": "median_profit", "mean": "mean_profit"})
            .reset_index()
            .rename(columns={"action_label_display": "action_label"})
        )
        st.dataframe(by_verdict, width="stretch", hide_index=True)

    if not retail_metrics_df.empty:
        retail_metrics = retail_metrics_df.iloc[0]
        metric_cols2 = st.columns(5)
        metric_cols2[0].metric("Rows tested", format_int(metric_value(retail_metrics, "rows")))
        metric_cols2[1].metric(prediction_count_label(retail_metrics), format_int(metric_value(retail_metrics, "buy_predictions")))
        metric_cols2[2].metric("Simulated profitable", format_int(metric_value(retail_metrics, "profitable_actuals")))
        metric_cols2[3].metric("Precision", format_ratio(metric_value(retail_metrics, "precision")))
        metric_cols2[4].metric("Recall", format_ratio(metric_value(retail_metrics, "recall")))

    display_columns2 = [
        "make",
        "model",
        "variant",
        "action_label",
        "resolved_action_label",
        "action_label_display",
        "policy_resolution_status",
        "computed_verdict",
        "bid_status",
        "hard_max_safety",
        "buy_price_basis_value",
        "retail_match_count",
        "simulated_retail_median",
        "simulated_profit",
        "url",
    ]
    display_columns2 = [column for column in display_columns2 if column in retail_outcomes_df.columns]
    st.dataframe(
        retail_outcomes_df.dropna(subset=["simulated_profit"])[display_columns2],
        width="stretch",
        hide_index=True,
    )


section_heading(
    "Historical Valuation Calibration",
    "Back-test the current auction-site proxy ceiling and profit rules against restricted sold outcomes.",
)
st.caption(
    "This evidence is read-only. It shows what the current rules would have done historically and does not change bidding rules."
)
calibration_controls = st.columns(2)
include_repairs = calibration_controls[0].checkbox("Include repair and risk costs", value=True)
fast_sample = calibration_controls[1].checkbox(
    "Fast 50-row sample",
    value=True,
    help="Keeps the proof page responsive. Turn this off when you specifically need the full historical calibration set.",
)
calibration_df = load_calibration(include_repairs, 50 if fast_sample else None)

if calibration_df.empty:
    st.warning("No calibration rows are available. Build restricted sold data and curves first.")
else:
    calibration_summary = summarize_calibration(calibration_df)
    calibration_metrics = st.columns(5)
    calibration_metrics[0].metric("Rows checked", format_int(calibration_summary.get("total_rows")))
    calibration_metrics[1].metric("Curve covered", format_int(calibration_summary.get("covered_rows")))
    calibration_metrics[2].metric(
        "Profitable within proxy max",
        format_int(calibration_summary.get("profitable_within_bid_rows")),
    )
    calibration_metrics[3].metric("Overbid risk", format_int(calibration_summary.get("overbid_risk_rows")))
    calibration_metrics[4].metric(
        "Priced-out winners",
        format_int(calibration_summary.get("priced_out_profitable_rows")),
    )

    profit_metrics = st.columns(2)
    profit_metrics[0].metric(
        "Theoretical profit within proxy max",
        format_money(calibration_summary.get("total_profitable_within_bid")),
    )
    profit_metrics[1].metric(
        "Average profit within proxy max",
        format_money(calibration_summary.get("avg_profit_within_bid")),
    )

    reason_options = sorted(calibration_df["calibration_reason"].dropna().astype(str).unique().tolist())
    selected_reasons = st.multiselect("Calibration reason", reason_options, default=reason_options)
    calibration_view = calibration_df[
        calibration_df["calibration_reason"].isin(selected_reasons)
    ].copy() if selected_reasons else calibration_df.copy()

    reason_tab, priced_out_tab, risk_tab, rows_tab = st.tabs(
        ["Reason Summary", "Priced-Out Winners", "Overbid Risk", "All Rows"]
    )
    with reason_tab:
        reason_summary = (
            calibration_view.groupby("calibration_reason", dropna=False)
            .agg(
                rows=("url", "count"),
                average_profit=("projected_profit_at_sold", "mean"),
                average_proxy_gap=("bid_gap", "mean"),
            )
            .reset_index()
            .sort_values("rows", ascending=False)
        )
        st.dataframe(reason_summary, width="stretch", hide_index=True)

    calibration_columns = [
        "year", "make", "model", "variant", "sold_price", "max_bid", "bid_gap",
        "projected_profit_at_sold", "repair_cost_estimate", "risk_buffer",
        "calibration_reason", "url",
    ]
    calibration_columns = [column for column in calibration_columns if column in calibration_view.columns]
    calibration_column_config = {
        "max_bid": st.column_config.NumberColumn("Proxy max", format="$%.0f"),
        "bid_gap": st.column_config.NumberColumn("Proxy-max gap", format="$%.0f"),
        "url": st.column_config.LinkColumn("Listing", display_text="Open"),
    }
    with priced_out_tab:
        priced_out_reasons = {"curve too conservative", "bid cap too conservative", "risk deduction too large"}
        priced_out = calibration_view[calibration_view["calibration_reason"].isin(priced_out_reasons)]
        st.dataframe(
            priced_out[calibration_columns],
            width="stretch",
            hide_index=True,
            column_config=calibration_column_config,
        )
    with risk_tab:
        overbid_risk = calibration_view[calibration_view["calibration_reason"] == "overbid risk"]
        if overbid_risk.empty:
            st.success("No overbid-risk rows in the current filtered view.")
        else:
            st.dataframe(
                overbid_risk[calibration_columns],
                width="stretch",
                hide_index=True,
                column_config=calibration_column_config,
            )
    with rows_tab:
        st.download_button(
            "Download filtered calibration CSV",
            data=calibration_view.to_csv(index=False).encode("utf-8"),
            file_name="valuation_calibration_filtered.csv",
            mime="text/csv",
        )
        st.dataframe(
            calibration_view[calibration_columns],
            width="stretch",
            hide_index=True,
            column_config=calibration_column_config,
        )
