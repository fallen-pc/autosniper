"""Shared helpers for valuation display and live-opportunity ranking."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


UNSAFE_VERDICT_KEYWORDS = (
    "avoid",
    "trap",
    "not covered",
    "not eligible",
    "not viable",
)


def parse_currency_value(value: Any) -> float | None:
    """Parse a currency-like value while preserving real zero values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    matches = re.findall(r"-?\d+(?:\.\d+)?", text)
    if not matches:
        return None
    numbers = [float(match) for match in matches]
    if len(numbers) > 1 and "-" in text:
        return sum(numbers) / len(numbers)
    return numbers[0]


def parse_percent_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).replace("%", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def first_currency_value(*values: Any) -> float | None:
    """Return the first parseable currency value; do not skip 0.0."""
    for value in values:
        parsed = parse_currency_value(value)
        if parsed is not None:
            return parsed
    return None


def first_percent_value(*values: Any) -> float | None:
    for value in values:
        parsed = parse_percent_value(value)
        if parsed is not None:
            return parsed
    return None


def _first_row_value(row: pd.Series, *columns: str) -> Any:
    for column in columns:
        if column in row.index:
            value = row.get(column)
            try:
                if pd.isna(value):
                    continue
            except (TypeError, ValueError):
                pass
            if value is not None and str(value).strip() != "":
                return value
    return None


def _truthy_flag(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def _is_safe_verdict(value: Any) -> bool:
    verdict = str(value or "").strip().lower()
    if not verdict:
        return False
    return not any(keyword in verdict for keyword in UNSAFE_VERDICT_KEYWORDS)


def rank_live_opportunities(active_df: pd.DataFrame, valuations_df: pd.DataFrame) -> pd.DataFrame:
    """Return ranked active listings that still have worst-case bidding edge."""
    if active_df.empty or valuations_df.empty or "url" not in active_df.columns or "url" not in valuations_df.columns:
        return pd.DataFrame()

    latest_valuations = valuations_df.copy()
    if "analysis_timestamp" in latest_valuations.columns:
        latest_valuations["analysis_timestamp"] = pd.to_datetime(
            latest_valuations["analysis_timestamp"],
            errors="coerce",
        )
        latest_valuations = latest_valuations.sort_values("analysis_timestamp")
    latest_valuations = latest_valuations.drop_duplicates("url", keep="last")

    merged = active_df.merge(latest_valuations, on="url", how="inner", suffixes=("", "_ai"))
    if merged.empty:
        return merged

    current_prices: list[float | None] = []
    max_bids: list[float | None] = []
    resale_values: list[float | None] = []
    worst_profits: list[float | None] = []
    margins: list[float | None] = []
    confidences: list[float] = []
    safe_rows: list[bool] = []

    for _, row in merged.iterrows():
        current_price = first_currency_value(
            _first_row_value(row, "current_bid_numeric", "current_bid", "price"),
            _first_row_value(row, "current_bid_numeric_ai", "current_bid_ai", "price_ai"),
        )
        max_bid = first_currency_value(
            _first_row_value(row, "recommended_max_bid", "recommended_max_bid_ai")
        )
        resale = first_currency_value(_first_row_value(row, "resale_mid", "resale_mid_ai"))
        worst_profit = first_currency_value(_first_row_value(row, "net_profit_worst", "net_profit_worst_ai"))
        margin = first_percent_value(_first_row_value(row, "profit_margin_percent", "profit_margin_percent_ai"))
        confidence_raw = _first_row_value(row, "confidence", "confidence_ai")
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0

        verdict = _first_row_value(row, "computed_verdict", "computed_verdict_ai", "verdict", "verdict_ai")
        no_edge = _truthy_flag(_first_row_value(row, "no_edge", "no_edge_ai", "no_edge_at_current_bid", "no_edge_at_current_bid_ai"))
        edge_buffer = first_currency_value(_first_row_value(row, "edge_buffer", "edge_buffer_ai")) or 50.0

        has_bid_edge = max_bid is not None and max_bid > 0
        if current_price is not None and max_bid is not None:
            has_bid_edge = has_bid_edge and max_bid > current_price + edge_buffer

        is_safe = (
            _is_safe_verdict(verdict)
            and not no_edge
            and has_bid_edge
            and worst_profit is not None
            and worst_profit > 0
        )

        current_prices.append(current_price)
        max_bids.append(max_bid)
        resale_values.append(resale)
        worst_profits.append(worst_profit)
        margins.append(margin)
        confidences.append(confidence)
        safe_rows.append(is_safe)

    merged = merged.copy()
    merged["current_price_value"] = current_prices
    merged["max_bid_value"] = max_bids
    merged["resale_mid_value"] = resale_values
    merged["profit_value"] = worst_profits
    merged["margin_value"] = margins
    merged["confidence_value"] = confidences
    merged = merged[pd.Series(safe_rows, index=merged.index)].copy()
    if merged.empty:
        return merged

    merged["potential_rank"] = (
        merged["profit_value"].fillna(0)
        + merged["margin_value"].fillna(0) * 50
        + merged["confidence_value"].fillna(0) * 1000
    )
    return merged.sort_values(by=["potential_rank"], ascending=False)
