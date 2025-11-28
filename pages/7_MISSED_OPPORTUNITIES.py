import pandas as pd
import streamlit as st

from scripts.ai_listing_valuation import load_cached_results
from scripts.ai_price_analysis import load_historical_sales
from shared.data_loader import ensure_datasets_available
from shared.styling import clean_html, display_banner, inject_global_styles


st.set_page_config(page_title="MISSED OPPORTUNITIES", layout="wide")
inject_global_styles()
display_banner()
st.markdown(
    clean_html(
        """
        <h1 style="text-align:center;">MISSED OPPORTUNITIES</h1>
        """
    ),
    unsafe_allow_html=True,
)
st.markdown(
    "<p class='autosniper-tagline'>Spot the listings that got away so you can refine bidding rules and sourcing playbooks.</p>",
    unsafe_allow_html=True,
)

required_files = ["ai_listing_valuations.csv", "sold_cars.csv"]
missing = ensure_datasets_available(required_files)
if missing:
    st.error(
        "Missing required datasets for analysis: "
        + ", ".join(missing)
        + ". Configure `AUTOSNIPER_DATA_URL` or upload the files to `CSV_data/`."
    )
    st.stop()


@st.cache_data(ttl=300)
def load_manual() -> pd.DataFrame:
    return load_cached_results()


def parse_currency(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_odometer(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).lower().replace("km", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def format_currency(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.0f}"


def format_odometer(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{int(round(value)):,} km"


manual_df = load_manual().copy()
if manual_df.empty:
    st.info("No manual Carsales data recorded yet.")
    st.stop()

sold_df = load_historical_sales().copy()
if sold_df.empty:
    st.info("No historical sale records available.")
    st.stop()

if "status" in sold_df.columns:
    status_series = sold_df["status"].astype(str).str.lower()
    has_sold_status = status_series == "sold"
    if has_sold_status.any():
        sold_df = sold_df[has_sold_status].copy()

manual_df["manual_avg_price"] = (
    manual_df["manual_carsales_estimate"]
    .fillna(manual_df["manual_carsales_avg"])
    .apply(parse_currency)
)
manual_df["manual_avg_odometer"] = manual_df["manual_carsales_avg_odometer"].apply(parse_odometer)
manual_df = manual_df.dropna(subset=["manual_avg_price"])
if manual_df.empty:
    st.info("No Carsales tables saved with an average price yet.")
    st.stop()

sold_df["final_sale_price"] = sold_df["final_price_numeric"].fillna(sold_df["price"])
sold_df["final_sale_price"] = sold_df["final_sale_price"].apply(parse_currency)
sold_df = sold_df.dropna(subset=["final_sale_price"])

opportunities = sold_df.merge(manual_df, on="url", how="inner")
opportunities = opportunities.drop_duplicates(subset=["url"], keep="last")
if opportunities.empty:
    st.info("No overlap between sold records and manual Carsales valuations yet.")
    st.stop()

opportunities["potential_profit"] = (
    opportunities["manual_avg_price"] - opportunities["final_sale_price"]
)
opportunities = opportunities[opportunities["potential_profit"] > 0].copy()

if opportunities.empty:
    st.info("No positive missed opportunities detected.")
    st.stop()

opportunities.sort_values(by="potential_profit", ascending=False, inplace=True)
opportunities.reset_index(drop=True, inplace=True)

st.subheader("Top Missed Opportunities")
cols = st.columns(3)
for idx, (_, row) in enumerate(opportunities.head(3).iterrows()):
    col = cols[idx]
    title = f"{int(row['year']) if pd.notna(row['year']) else ''} {row['make']} {row['model']}"
    col.markdown(f"**{title}**")
    col.write(row.get("variant", ""))
    col.metric(
        label="Potential Profit",
        value=format_currency(row["potential_profit"]),
        delta=f"Sold for {format_currency(row['final_sale_price'])}",
    )
    col.write(f"Carsales estimate: {format_currency(row['manual_avg_price'])}")
    if pd.notna(row.get("date_sold")):
        col.caption(f"Date sold: {row['date_sold']}")
    col.markdown(f"[View Listing]({row['url']})")

st.subheader("All Positive Opportunities")
display_cols = [
    "year",
    "make",
    "model",
    "variant",
    "final_sale_price",
    "manual_avg_price",
    "potential_profit",
    "manual_avg_odometer",
    "date_sold",
    "url",
]
existing_cols = [col for col in display_cols if col in opportunities.columns]
display_df = opportunities[existing_cols].copy()
display_df["final_sale_price"] = display_df["final_sale_price"].apply(format_currency)
display_df["manual_avg_price"] = display_df["manual_avg_price"].apply(format_currency)
display_df["potential_profit"] = display_df["potential_profit"].apply(format_currency)
if "manual_avg_odometer" in display_df.columns:
    display_df["manual_avg_odometer"] = display_df["manual_avg_odometer"].apply(
        format_odometer
    )

st.dataframe(display_df, width="stretch")
