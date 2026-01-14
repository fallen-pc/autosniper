import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path, ensure_datasets_available
from shared.styling import inject_global_styles, page_intro


st.set_page_config(page_title="Re-Auction Tracker", layout="wide")
inject_global_styles()
page_intro(
    "RE-AUCTION TRACKER",
    "Monitor vehicles that re-appear in the sold dataset with the same VIN and odometer to understand pricing swings.",
)


def _coerce_price(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_odometer(text: object) -> float | None:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return None
    cleaned = "".join(ch for ch in str(text) if ch.isdigit() or ch == ".")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


@st.cache_data(ttl=600)
def load_reauction_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    ensure_datasets_available(["sold_cars.csv"])
    sold_path = dataset_path("sold_cars.csv")
    df = pd.read_csv(sold_path)

    price_columns = [col for col in ["final_price", "price", "sold_price", "hammer_price"] if col in df.columns]
    if "final_price_numeric" in df.columns:
        df["price_numeric"] = df["final_price_numeric"]
    elif price_columns:
        df["price_numeric"] = df[price_columns[0]].apply(_coerce_price)
        for column in price_columns[1:]:
            fallback = df[column].apply(_coerce_price)
            df["price_numeric"] = df["price_numeric"].fillna(fallback)
    else:
        df["price_numeric"] = None

    df["vin_norm"] = df.get("vin", pd.Series([None] * len(df))).astype(str).str.strip().str.lower()
    df["vin_norm"] = df["vin_norm"].replace({"": pd.NA})
    df["odometer_numeric"] = df.get("odometer_numeric", pd.Series([None] * len(df))).copy()
    if df["odometer_numeric"].isna().all() and "odometer_reading" in df.columns:
        df["odometer_numeric"] = df["odometer_reading"].apply(_parse_odometer)
    df["date_sold"] = df.get("date_sold", pd.Series([None] * len(df)))
    df["date_sold_text"] = df["date_sold"].fillna("").astype(str)

    valid_mask = (
        df["vin_norm"].notna()
        & df["odometer_numeric"].notna()
        & df["price_numeric"].notna()
    )
    subset = df.loc[valid_mask].copy()
    if subset.empty:
        return pd.DataFrame(), pd.DataFrame()

    summary = (
        subset.groupby(["vin_norm", "odometer_numeric"])
        .agg(
            count=("vin_norm", "size"),
            make=("make", "first"),
            model=("model", "first"),
            variant=("variant", "first"),
            min_price=("price_numeric", "min"),
            max_price=("price_numeric", "max"),
            first_date=("date_sold_text", "min"),
            last_date=("date_sold_text", "max"),
        )
        .reset_index()
    )

    summary = summary[summary["count"] >= 2].copy()
    if summary.empty:
        return pd.DataFrame(), pd.DataFrame()

    summary["price_range"] = summary["max_price"] - summary["min_price"]
    summary["vin_display"] = summary["vin_norm"].str.upper()
    summary["odometer_display"] = summary["odometer_numeric"].apply(
        lambda val: f"{int(val):,} km" if pd.notna(val) else "N/A"
    )
    summary.sort_values(by=["price_range", "count"], ascending=[False, False], inplace=True)
    subset["price_display"] = subset["price_numeric"].apply(
        lambda val: f"${val:,.0f}" if pd.notna(val) else "N/A"
    )

    return summary.reset_index(drop=True), subset.reset_index(drop=True)


summary_df, detail_df = load_reauction_data()

if summary_df.empty:
    st.info("No duplicate VIN + odometer combinations detected in the sold dataset.")
    st.stop()

st.sidebar.header("Filters")
min_count = st.sidebar.slider("Minimum re-auction count", min_value=2, max_value=6, value=2, step=1)
min_range = st.sidebar.number_input("Minimum price swing ($)", min_value=0, value=0, step=1000)

filtered_summary = summary_df[
    (summary_df["count"] >= min_count) & (summary_df["price_range"] >= float(min_range))
].copy()

st.caption(
    f"{len(filtered_summary)} groups match the filters (from {len(summary_df)} total duplicate VIN groups)."
)

if filtered_summary.empty:
    st.warning("No re-auction groups meet the current filters. Adjust them to see results.")
    st.stop()

display_columns = [
    "vin_display",
    "odometer_display",
    "count",
    "min_price",
    "max_price",
    "price_range",
    "first_date",
    "last_date",
    "make",
    "model",
    "variant",
]
table = filtered_summary[display_columns].rename(
    columns={
        "vin_display": "VIN",
        "odometer_display": "Odometer",
        "count": "Events",
        "min_price": "Min Price",
        "max_price": "Max Price",
        "price_range": "Price Range",
        "first_date": "First Sale",
        "last_date": "Last Sale",
        "make": "Make",
        "model": "Model",
        "variant": "Variant",
    }
)
currency_cols = ["Min Price", "Max Price", "Price Range"]
for col in currency_cols:
    table[col] = table[col].apply(lambda val: f"${val:,.0f}" if pd.notna(val) else "N/A")

st.dataframe(table, use_container_width=True)

st.subheader("Re-Auction History")
for row_index, (_, summary_row) in enumerate(filtered_summary.iterrows(), start=1):
    label = (
        f"{row_index}. {summary_row['vin_display']} — {summary_row['odometer_display']} "
        f"({int(summary_row['count'])} events, ${summary_row['price_range']:,.0f} swing)"
    )
    with st.expander(label):
        history_rows = detail_df[
            (detail_df["vin_norm"] == summary_row["vin_norm"])
            & (detail_df["odometer_numeric"] == summary_row["odometer_numeric"])
        ].copy()
        if history_rows.empty:
            st.info("No sale history available for this group.")
            continue
        history_rows.sort_values(by="date_sold", inplace=True)
        history_rows["date_display"] = history_rows["date_sold"].fillna("Unknown date")
        if "location" in history_rows.columns:
            history_rows["location"] = history_rows["location"].fillna("N/A")
        else:
            history_rows["location"] = "N/A"
        if "status" not in history_rows.columns:
            history_rows["status"] = ""
        else:
            history_rows["status"] = history_rows["status"].fillna("")

        entries: list[str] = []
        for _, record in history_rows.iterrows():
            date_text = record.get("date_display", "Unknown date")
            price_text = record.get("price_display", "N/A")
            location_text = record.get("location", "N/A")
            status_text = record.get("status", "")
            url_value = record.get("url", "")
            entry = f"- **{date_text}** — {price_text} ({location_text}"
            if status_text:
                entry += f", {status_text}"
            entry += ")"
            if isinstance(url_value, str) and url_value.strip():
                entry += f" [Open listing]({url_value.strip()})"
            entries.append(entry)

        st.markdown("\n".join(entries))
