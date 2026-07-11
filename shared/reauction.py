"""Helpers for vehicles that re-appear at auction with the same VIN/odometer."""

from __future__ import annotations

from typing import Any

import pandas as pd


REAUCTION_KEY_COLUMNS = ["vin_norm", "odometer_numeric"]


def coerce_price(value: Any) -> float | None:
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


def parse_odometer(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    cleaned = "".join(ch for ch in str(value) if ch.isdigit() or ch == ".")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_vin(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().upper()
    if text.lower() in {"", "nan", "none", "n/a"}:
        return ""
    return text


def prepare_reauction_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with normalized fields used for re-auction grouping."""

    working = df.copy()
    if "price_numeric" not in working.columns:
        price_columns = [
            col
            for col in ("final_price", "price", "sold_price", "hammer_price")
            if col in working.columns
        ]
        if price_columns:
            working["price_numeric"] = working[price_columns[0]].apply(coerce_price)
            for column in price_columns[1:]:
                working["price_numeric"] = working["price_numeric"].fillna(
                    working[column].apply(coerce_price)
                )
        else:
            working["price_numeric"] = pd.NA
    else:
        working["price_numeric"] = pd.to_numeric(working["price_numeric"], errors="coerce")

    working["vin_norm"] = working.get(
        "vin", pd.Series([None] * len(working), index=working.index)
    ).apply(normalize_vin)

    if "odometer_numeric" in working.columns:
        working["odometer_numeric"] = pd.to_numeric(working["odometer_numeric"], errors="coerce")
    else:
        working["odometer_numeric"] = pd.NA
    if working["odometer_numeric"].isna().any() and "odometer_reading" in working.columns:
        fallback_odo = pd.to_numeric(working["odometer_reading"].apply(parse_odometer), errors="coerce")
        missing_odo = working["odometer_numeric"].isna()
        working.loc[missing_odo, "odometer_numeric"] = fallback_odo.loc[missing_odo]
        working["odometer_numeric"] = pd.to_numeric(working["odometer_numeric"], errors="coerce")

    working["date_sold_parsed"] = pd.to_datetime(working.get("date_sold"), errors="coerce")
    working["reauction_key"] = ""
    valid_key = working["vin_norm"].ne("") & working["odometer_numeric"].notna()
    working.loc[valid_key, "reauction_key"] = (
        working.loc[valid_key, "vin_norm"]
        + "|"
        + working.loc[valid_key, "odometer_numeric"].round(0).astype("Int64").astype(str)
    )
    return working


def build_reauction_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Summarize repeated VIN/odometer sale lifecycles."""

    working = prepare_reauction_frame(df)
    valid = working[
        working["vin_norm"].ne("")
        & working["odometer_numeric"].notna()
        & working["price_numeric"].notna()
    ].copy()
    if valid.empty:
        return pd.DataFrame()

    valid["_date_sort"] = valid["date_sold_parsed"].fillna(pd.Timestamp.min)
    summary = (
        valid.sort_values(["vin_norm", "odometer_numeric", "_date_sort", "price_numeric"])
        .groupby(REAUCTION_KEY_COLUMNS, dropna=False)
        .agg(
            reauction_event_count=("vin_norm", "size"),
            reauction_first_price=("price_numeric", "first"),
            reauction_last_price=("price_numeric", "last"),
            reauction_min_price=("price_numeric", "min"),
            reauction_max_price=("price_numeric", "max"),
            reauction_first_date=("date_sold_parsed", "first"),
            reauction_last_date=("date_sold_parsed", "last"),
        )
        .reset_index()
    )
    summary = summary[summary["reauction_event_count"] >= 2].copy()
    if summary.empty:
        return summary
    summary["reauction_price_range"] = (
        summary["reauction_max_price"] - summary["reauction_min_price"]
    )
    summary["reauction_price_delta"] = (
        summary["reauction_last_price"] - summary["reauction_first_price"]
    )
    return summary


def collapse_reauction_lifecycles(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse repeated VIN/odometer sold rows to the latest sale event.

    Rows without a usable VIN/odometer key are preserved as-is. Repeated lifecycle
    rows carry summary columns so downstream pages can show that the retained row
    represents multiple auction events.
    """

    working = prepare_reauction_frame(df)
    if working.empty:
        return working

    summary = build_reauction_summary(working)
    working["_date_sort"] = working["date_sold_parsed"].fillna(pd.Timestamp.min)
    valid_key = working["reauction_key"].ne("")
    keyed = (
        working[valid_key]
        .sort_values(["reauction_key", "_date_sort", "price_numeric"])
        .drop_duplicates("reauction_key", keep="last")
    )
    unkeyed = working[~valid_key].copy()
    collapsed = pd.concat([keyed, unkeyed], ignore_index=True)

    if not summary.empty:
        collapsed = collapsed.merge(
            summary,
            on=REAUCTION_KEY_COLUMNS,
            how="left",
            suffixes=("", "_summary"),
        )

    if "reauction_event_count" not in collapsed.columns:
        collapsed["reauction_event_count"] = 1
    collapsed["reauction_event_count"] = collapsed["reauction_event_count"].fillna(1).astype(int)
    for column in (
        "reauction_first_price",
        "reauction_last_price",
        "reauction_min_price",
        "reauction_max_price",
        "reauction_price_range",
        "reauction_price_delta",
    ):
        if column not in collapsed.columns:
            collapsed[column] = pd.NA

    return collapsed.drop(columns=["_date_sort"], errors="ignore")


def reauction_context_for_listing(
    listing: pd.Series | dict[str, Any],
    sold_df: pd.DataFrame,
) -> dict[str, Any]:
    """Return re-auction context for an active listing's VIN/odometer."""

    if sold_df.empty:
        return {}
    listing_df = prepare_reauction_frame(pd.DataFrame([dict(listing)]))
    if listing_df.empty:
        return {}
    key = str(listing_df.iloc[0].get("reauction_key") or "")
    if not key:
        return {}

    sold = prepare_reauction_frame(sold_df)
    matches = sold[sold["reauction_key"] == key].copy()
    matches = matches[matches["price_numeric"].notna()]
    if matches.empty:
        return {}
    matches = matches.sort_values(["date_sold_parsed", "price_numeric"])
    prices = matches["price_numeric"].dropna()
    last = matches.iloc[-1]
    first = matches.iloc[0]
    event_count = int(last.get("reauction_event_count") or len(matches))
    first_price = last.get("reauction_first_price")
    last_price = last.get("reauction_last_price")
    price_delta = last.get("reauction_price_delta")
    price_range = last.get("reauction_price_range")
    if pd.isna(first_price):
        first_price = first["price_numeric"]
    if pd.isna(last_price):
        last_price = last["price_numeric"]
    if pd.isna(price_delta):
        price_delta = float(last_price) - float(first_price)
    if pd.isna(price_range):
        price_range = float(prices.max() - prices.min())
    return {
        "reauction_event_count": event_count,
        "reauction_last_price": float(last_price),
        "reauction_first_price": float(first_price),
        "reauction_min_price": float(prices.min()),
        "reauction_max_price": float(prices.max()),
        "reauction_price_delta": float(price_delta),
        "reauction_price_range": float(price_range),
        "reauction_last_date": last.get("date_sold"),
        "reauction_first_date": first.get("date_sold"),
    }


def adjusted_expected_auction_price(
    base_price: float | None,
    context: dict[str, Any] | None,
) -> tuple[float | None, float, str]:
    """Apply a conservative finish-price adjustment for active re-auctions.

    Historical repeats usually clear lower on the next run. When the same
    VIN/odometer has already sold, cap the expected finish at the latest sold
    price if that is below the normal estimate. If the latest sale was higher,
    keep the normal estimate and expose a zero adjustment.
    """

    if base_price is None or not context:
        return base_price, 0.0, ""
    try:
        event_count = int(context.get("reauction_event_count") or 0)
        last_price = float(context.get("reauction_last_price"))
    except (TypeError, ValueError):
        return base_price, 0.0, ""
    if event_count < 1 or last_price <= 0:
        return base_price, 0.0, ""
    adjusted = min(float(base_price), last_price)
    adjustment = adjusted - float(base_price)
    reason = "reauction_latest_sale_cap" if adjustment < 0 else "reauction_history_no_cap"
    return adjusted, adjustment, reason
