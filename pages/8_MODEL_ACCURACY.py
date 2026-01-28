from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path, ensure_datasets_available
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Model Accuracy", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "MODEL ACCURACY",
    "Review how scored listings performed once they settle.",
    show_logo=False,
)

missing = ensure_datasets_available(["scored_listings.csv"])
if missing:
    st.error(
        "Required dataset `scored_listings.csv` is missing. "
        "Run the model audit pipeline or sync the data bundle."
    )
    st.stop()

SCORED_FILE = dataset_path("scored_listings.csv")
WEEKLY_FILE = dataset_path("model_accuracy_weekly.csv")
TIER_FILE = dataset_path("model_accuracy_by_tier.csv")


@st.cache_data(ttl=300)
def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not read {path.name}: {exc}")
        return pd.DataFrame()


def coerce_bool(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype="boolean")
    if series.dtype == bool:
        return series
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any():
        return numeric.map(lambda value: True if value == 1 else False if value == 0 else pd.NA)
    text = series.astype(str).str.strip().str.lower()
    return text.map({"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False})


def format_currency(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"${float(value):,.0f}"


def format_ratio(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    ratio = float(value)
    return f"{ratio * 100:.1f}%"


def format_percent(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    pct = float(value)
    if abs(pct) <= 1:
        pct *= 100
    return f"{pct:.1f}%"


def format_datetime(value: datetime | pd.Timestamp | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    return value.strftime("%d %b %Y %H:%M")


scored_df = load_csv(SCORED_FILE)
weekly_df = load_csv(WEEKLY_FILE)
tier_df = load_csv(TIER_FILE)

if scored_df.empty:
    st.info("No scored listings found yet. Run the model audit pipeline to populate this page.")
    st.stop()

if "analysis_timestamp" in scored_df.columns:
    scored_df["analysis_timestamp"] = pd.to_datetime(scored_df["analysis_timestamp"], errors="coerce")
if "settled_date" in scored_df.columns:
    scored_df["settled_date"] = pd.to_datetime(scored_df["settled_date"], errors="coerce")

hit_series = coerce_bool(scored_df["hit"]) if "hit" in scored_df.columns else pd.Series(pd.NA, index=scored_df.index)
valid_hits = hit_series[hit_series.notna()]

settled_mask = pd.Series(False, index=scored_df.index)
if "hit" in scored_df.columns:
    settled_mask = hit_series.notna()
if "actual_sale_price" in scored_df.columns:
    settled_mask |= pd.to_numeric(scored_df["actual_sale_price"], errors="coerce").notna()
if "settled_date" in scored_df.columns:
    settled_mask |= scored_df["settled_date"].notna()

error_abs = (
    pd.to_numeric(scored_df["outcome_error_abs"], errors="coerce")
    if "outcome_error_abs" in scored_df.columns
    else pd.Series(dtype="float")
)
error_pct = (
    pd.to_numeric(scored_df["outcome_error_pct"], errors="coerce")
    if "outcome_error_pct" in scored_df.columns
    else pd.Series(dtype="float")
)

mae_price = error_abs[settled_mask].abs().mean() if not error_abs.empty else None
mape_price = error_pct[settled_mask].abs().mean() if not error_pct.empty else None

profit_pred = (
    coerce_bool(scored_df["is_profitable_pred"]) if "is_profitable_pred" in scored_df.columns else None
)
profit_actual = (
    coerce_bool(scored_df["is_profitable_actual"]) if "is_profitable_actual" in scored_df.columns else None
)
profit_match = None
if profit_pred is not None and profit_actual is not None:
    match_series = pd.Series(pd.NA, index=scored_df.index)
    match_mask = profit_pred.notna() & profit_actual.notna()
    match_series.loc[match_mask] = profit_pred.loc[match_mask] == profit_actual.loc[match_mask]
    profit_match = match_series
    profit_calibration = match_series.dropna().astype(float).mean() if match_mask.any() else None
else:
    profit_calibration = None

analysis_latest = scored_df["analysis_timestamp"].max() if "analysis_timestamp" in scored_df.columns else None
settled_latest = scored_df["settled_date"].max() if "settled_date" in scored_df.columns else None

section_heading("Accuracy Snapshot", "Coverage for settled listings and pricing error.")
metrics = st.columns(6)
metrics[0].metric("Scored listings", f"{len(scored_df):,}")
metrics[1].metric("Settled outcomes", f"{len(valid_hits):,}")
metrics[2].metric("Hit accuracy", format_ratio(valid_hits.astype(float).mean()) if not valid_hits.empty else "N/A")
metrics[3].metric("MAE price", format_currency(mae_price))
metrics[4].metric("MAPE price", format_percent(mape_price))
metrics[5].metric("Profit match", format_ratio(profit_calibration))

st.caption(
    f"Latest analysis: {format_datetime(analysis_latest)} | Latest settled: {format_datetime(settled_latest)}"
)

section_heading("Accuracy Trend", "Weekly model accuracy and pricing error.")


def build_weekly_fallback(frame: pd.DataFrame, hits: pd.Series) -> pd.DataFrame:
    if "settled_date" not in frame.columns:
        return pd.DataFrame()
    working = frame.copy()
    working["hit_bool"] = hits
    working = working[working["settled_date"].notna() & working["hit_bool"].notna()]
    if working.empty:
        return pd.DataFrame()
    if "outcome_error_abs" in working.columns:
        working["outcome_error_abs"] = pd.to_numeric(working["outcome_error_abs"], errors="coerce")
    if "outcome_error_pct" in working.columns:
        working["outcome_error_pct"] = pd.to_numeric(working["outcome_error_pct"], errors="coerce")
    if profit_match is not None:
        working["profit_match"] = profit_match
    working["week"] = working["settled_date"].dt.to_period("W").apply(lambda period: period.start_time)
    grouped = working.groupby("week")
    summary = grouped["hit_bool"].mean().rename("accuracy").to_frame()
    summary["count"] = grouped["hit_bool"].size()
    if "outcome_error_abs" in working.columns:
        summary["mae_price"] = grouped["outcome_error_abs"].mean()
    if "outcome_error_pct" in working.columns:
        summary["mape_price"] = grouped["outcome_error_pct"].mean()
    if "profit_match" in working.columns:
        summary["profit_calibration"] = grouped["profit_match"].mean()
    return summary.reset_index()


if weekly_df.empty:
    weekly_df = build_weekly_fallback(scored_df, hit_series)

if weekly_df.empty:
    st.info("Weekly accuracy data is not available yet.")
else:
    display_weekly = weekly_df.copy()
    if "accuracy" in display_weekly.columns:
        display_weekly["accuracy"] = display_weekly["accuracy"].apply(format_ratio)
    if "mae_price" in display_weekly.columns:
        display_weekly["mae_price"] = display_weekly["mae_price"].apply(format_currency)
    if "mape_price" in display_weekly.columns:
        display_weekly["mape_price"] = display_weekly["mape_price"].apply(format_percent)
    if "profit_calibration" in display_weekly.columns:
        display_weekly["profit_calibration"] = display_weekly["profit_calibration"].apply(format_ratio)
    st.dataframe(display_weekly, width="stretch", hide_index=True)

section_heading("Verdict Performance", "How predictions perform by verdict tier.")


def build_tier_fallback(frame: pd.DataFrame, hits: pd.Series) -> pd.DataFrame:
    if "predicted_verdict" not in frame.columns:
        return pd.DataFrame()
    working = frame.copy()
    working["hit_bool"] = hits
    working = working[working["hit_bool"].notna()]
    if working.empty:
        return pd.DataFrame()

    def summarize(group: pd.DataFrame) -> pd.Series:
        summary: dict[str, float | int] = {
            "accuracy": group["hit_bool"].mean(),
            "count": int(group["hit_bool"].size),
        }
        if "outcome_error_abs" in group.columns:
            summary["mae_price"] = pd.to_numeric(group["outcome_error_abs"], errors="coerce").mean()
        return pd.Series(summary)

    return working.groupby("predicted_verdict", dropna=False).apply(summarize).reset_index()


if tier_df.empty:
    tier_df = build_tier_fallback(scored_df, hit_series)

if tier_df.empty:
    st.info("Verdict accuracy breakdown is not available yet.")
else:
    display_tier = tier_df.copy()
    if "accuracy" in display_tier.columns:
        display_tier["accuracy"] = display_tier["accuracy"].apply(format_ratio)
    if "mae_price" in display_tier.columns:
        display_tier["mae_price"] = display_tier["mae_price"].apply(format_currency)
    st.dataframe(display_tier, width="stretch", hide_index=True)

section_heading("Settled Listings", "Sample of settled outcomes and model deltas.")

only_settled = st.checkbox("Show settled only", value=True)
view_df = scored_df.copy()
if only_settled:
    view_df = view_df[settled_mask]

verdicts = []
if "predicted_verdict" in view_df.columns:
    verdicts = sorted({str(value) for value in view_df["predicted_verdict"].dropna() if str(value).strip()})
if verdicts:
    verdict_choice = st.selectbox("Predicted verdict", ["All"] + verdicts, index=0)
    if verdict_choice != "All":
        view_df = view_df[view_df["predicted_verdict"].astype(str) == verdict_choice]

row_limit = st.selectbox("Rows", [25, 50, 100, 250], index=1)
display_columns = [
    "analysis_timestamp",
    "settled_date",
    "year",
    "make",
    "model",
    "variant",
    "predicted_verdict",
    "predicted_score",
    "purchase_price",
    "actual_sale_price",
    "actual_profit",
    "outcome_error_abs",
    "outcome_error_pct",
    "hit",
    "url",
]
display_columns = [column for column in display_columns if column in view_df.columns]
if view_df.empty:
    st.info("No listings match the current filters.")
else:
    st.dataframe(view_df[display_columns].head(row_limit), width="stretch", hide_index=True)
