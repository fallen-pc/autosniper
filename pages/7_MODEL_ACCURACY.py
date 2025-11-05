import altair as alt
import pandas as pd
import streamlit as st

from scripts.outcome_tracking import compute_outcome_metrics
from shared.styling import clean_html, display_banner, inject_global_styles


st.set_page_config(page_title="OUTCOME ACCURACY", layout="wide")
inject_global_styles()
display_banner()

st.markdown(
    clean_html(
        """
        <h1 style="text-align:center;">OUTCOME ACCURACY TRACKER</h1>
        """
    ),
    unsafe_allow_html=True,
)
st.markdown(
    "<p class='autosniper-tagline'>See how well predictions lined up with real-world results so you can tighten bids and confidence bands.</p>",
    unsafe_allow_html=True,
)


def _format_currency(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"${value:,.0f}"


def _format_percent(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value * 100:,.1f}%"


with st.spinner("Updating scored listings and accuracy metrics..."):
    outcome_data = compute_outcome_metrics()

scored_df = outcome_data.scored.copy()
evaluated_df = scored_df[scored_df["hit"].notna()].copy()

total_scored = len(scored_df)
settled_count = len(evaluated_df)
accuracy = evaluated_df["hit"].mean() if settled_count else None
mae = evaluated_df["outcome_error_abs"].mean() if settled_count else None
mape = evaluated_df["outcome_error_pct"].mean() if settled_count else None
profit_calibration = evaluated_df["actual_profit"].mean() if settled_count else None

metrics_cols = st.columns(4)
metrics_cols[0].metric("Total Scored Listings", f"{total_scored:,}")
metrics_cols[1].metric("Recorded Outcomes", f"{settled_count:,}")
metrics_cols[2].metric("Accuracy", _format_percent(accuracy))
metrics_cols[3].metric("Profit Calibration", _format_currency(profit_calibration))

sub_cols = st.columns(2)
sub_cols[0].metric("MAE (Price)", _format_currency(mae))
sub_cols[1].metric("MAPE (Price)", _format_percent(mape))

st.markdown("---")

left_col, right_col = st.columns([2, 1])

with left_col:
    st.subheader("Weekly Hit Rate")
    weekly_df = outcome_data.weekly_metrics.copy()
    if weekly_df.empty:
        st.info("Log a few settled resale outcomes to start tracking accuracy over time.")
    else:
        weekly_df["accuracy_pct"] = weekly_df["accuracy"] * 100
        line_chart = (
            alt.Chart(weekly_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("week:T", title="Week starting"),
                y=alt.Y("accuracy_pct:Q", title="Accuracy (%)", scale=alt.Scale(domain=[0, 100])),
                tooltip=[
                    alt.Tooltip("week:T", title="Week"),
                    alt.Tooltip("accuracy_pct:Q", title="Accuracy", format=".1f"),
                    alt.Tooltip("mae_price:Q", title="MAE", format=",.0f"),
                    alt.Tooltip("mape_price:Q", title="MAPE", format=".2%"),
                    alt.Tooltip("profit_calibration:Q", title="Profit Calibration", format=",.0f"),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(line_chart, use_container_width=True)

with right_col:
    st.subheader("Tier Hit Rate")
    tier_df = outcome_data.tier_metrics.copy()
    if tier_df.empty:
        st.info("No verdict tiers have matched with actual profit outcomes yet.")
    else:
        tier_df["accuracy_pct"] = tier_df["accuracy"] * 100
        tier_chart = (
            alt.Chart(tier_df.assign(metric="Accuracy"))
            .mark_rect()
            .encode(
                x=alt.X("metric:N", title="", axis=alt.Axis(labels=False, ticks=False)),
                y=alt.Y("predicted_verdict:N", title="Predicted Verdict"),
                color=alt.Color(
                    "accuracy_pct:Q",
                    title="Accuracy (%)",
                    scale=alt.Scale(domain=[0, 100], scheme="blues"),
                ),
                tooltip=[
                    alt.Tooltip("predicted_verdict:N", title="Verdict"),
                    alt.Tooltip("accuracy_pct:Q", title="Accuracy", format=".1f"),
                    alt.Tooltip("count:Q", title="Count"),
                    alt.Tooltip("mae_price:Q", title="MAE", format=",.0f"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(tier_chart, use_container_width=True)

st.markdown("---")
st.subheader("Worst Misses")
misses_df = outcome_data.misses.copy()
if misses_df.empty:
    st.info("No recorded misses yet. Add actual resale prices once deals settle to surface the biggest gaps.")
else:
    display_df = misses_df.copy()
    display_df["predicted_resale_price"] = display_df["predicted_resale_price"].apply(_format_currency)
    display_df["actual_sale_price"] = display_df["actual_sale_price"].apply(_format_currency)
    display_df["outcome_error_abs"] = display_df["outcome_error_abs"].apply(_format_currency)
    display_df["outcome_error_pct"] = display_df["outcome_error_pct"].apply(lambda value: f"{value * 100:,.1f}%" if pd.notna(value) else "N/A")
    st.dataframe(display_df, use_container_width=True)

st.markdown("---")
st.subheader("Raw Data Snapshots")
with st.expander("Scored Listings (first 200 rows)"):
    preview_cols = [
        "url",
        "predicted_resale_price",
        "predicted_profit",
        "predicted_verdict",
        "recommended_max_bid",
        "purchase_price",
        "actual_sale_price",
        "actual_profit",
        "hit",
        "settled_date",
    ]
    existing_cols = [col for col in preview_cols if col in scored_df.columns]
    st.dataframe(scored_df[existing_cols].head(200), use_container_width=True)

download_cols = st.columns(4)
download_cols[0].markdown("Download CSV exports")
download_cols[1].download_button(
    "Scored Listings",
    scored_df.to_csv(index=False),
    file_name="scored_listings.csv",
)
download_cols[2].download_button(
    "Weekly Metrics",
    outcome_data.weekly_metrics.to_csv(index=False),
    file_name="model_accuracy_weekly.csv",
)
download_cols[3].download_button(
    "Verdict Metrics",
    outcome_data.tier_metrics.to_csv(index=False),
    file_name="model_accuracy_by_tier.csv",
)
