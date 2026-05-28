"""Shared helpers for valuation display and live-opportunity ranking."""

from __future__ import annotations

import re
from typing import Any, Mapping

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


def conservative_margin_percent(row: Mapping[str, Any]) -> float | None:
    """Return a conservative profit margin, preferring worst-case profit over stored text."""
    resale = first_currency_value(
        row.get("resale_mid"),
        row.get("resale_mid_ai"),
        row.get("expected_sale"),
        row.get("expected_sale_ai"),
        row.get("resale_value"),
        row.get("resale_mid_value"),
    )
    if resale is not None and resale > 0:
        worst_profit = first_currency_value(
            row.get("net_profit_worst"),
            row.get("net_profit_worst_ai"),
            row.get("expected_auction_worst_profit"),
            row.get("expected_auction_worst_profit_ai"),
            row.get("profit_value"),
        )
        if worst_profit is not None:
            return (worst_profit / resale) * 100.0

        mid_profit = first_currency_value(
            row.get("net_profit_mid"),
            row.get("net_profit_mid_ai"),
            row.get("expected_profit"),
            row.get("expected_profit_ai"),
        )
        if mid_profit is not None:
            return (mid_profit / resale) * 100.0

    return first_percent_value(
        row.get("profit_margin_percent"),
        row.get("profit_margin_percent_ai"),
        row.get("profit_margin_value"),
        row.get("margin_value"),
    )


def active_profit_value(row: Mapping[str, Any]) -> float | None:
    """Return the best available live-opportunity profit, preferring explicit newer fields."""
    return first_currency_value(
        row.get("net_profit_worst"),
        row.get("net_profit_worst_ai"),
        row.get("expected_auction_worst_profit"),
        row.get("expected_auction_worst_profit_ai"),
        row.get("net_profit_mid"),
        row.get("net_profit_mid_ai"),
        row.get("expected_auction_profit"),
        row.get("expected_auction_profit_ai"),
        row.get("expected_profit"),
        row.get("expected_profit_ai"),
        row.get("profit_at_current_bid_worst"),
        row.get("profit_at_current_bid"),
        row.get("profit_value"),
    )


def expected_finish_profit_value(row: Mapping[str, Any]) -> float | None:
    """Return the best available expected-finish profit for calibration/tracking."""
    return first_currency_value(
        row.get("expected_auction_profit"),
        row.get("expected_auction_profit_ai"),
        row.get("expected_profit"),
        row.get("expected_profit_ai"),
    )


def recommended_max_bid_value(row: Mapping[str, Any]) -> float | None:
    """Return only a real recommended max bid; do not fall back to current price."""
    return first_currency_value(
        row.get("recommended_max_bid"),
        row.get("recommended_max_bid_ai"),
        row.get("max_bid"),
    )


def economic_max_bid_value(row: Mapping[str, Any]) -> float | None:
    """Return the pre-policy economic max bid, falling back to the policy bid."""
    return first_currency_value(
        row.get("economic_max_bid"),
        row.get("economic_max_bid_ai"),
        row.get("recommended_max_bid"),
        row.get("recommended_max_bid_ai"),
        row.get("max_bid"),
    )


def current_bid_value(row: Mapping[str, Any]) -> float | None:
    """Return the current live bid/price used for bid-room display."""
    return first_currency_value(
        row.get("current_bid_numeric"),
        row.get("current_bid"),
        row.get("current_bid_numeric_ai"),
        row.get("current_bid_ai"),
        row.get("price"),
        row.get("price_ai"),
    )


def _currency_text(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.0f}"


def _clean_display_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "n/a"}:
        return ""
    return text


def bid_display_parts(row: Mapping[str, Any]) -> dict[str, str]:
    """Return concise bid wording without hiding pre-policy economics."""
    policy_bid = recommended_max_bid_value(row)
    economic_bid = economic_max_bid_value(row)
    current_bid = current_bid_value(row)
    policy_gate = _clean_display_text(row.get("bid_policy_gate") or row.get("bid_policy_gate_ai")).upper()
    raw_status = _clean_display_text(row.get("bid_status") or row.get("bid_status_ai")) or "Unknown"

    no_policy_bid = policy_bid is not None and policy_bid <= 0
    economics_visible = economic_bid is not None and economic_bid > 0
    if policy_gate:
        status = "Policy blocked"
        if economics_visible:
            status_detail = f"{policy_gate.title()} policy; economics cap {_currency_text(economic_bid)}"
        else:
            status_detail = f"{policy_gate.title()} policy; economics unavailable"
    elif no_policy_bid and economics_visible:
        status = "No policy bid"
        status_detail = f"Economics cap {_currency_text(economic_bid)} still visible"
    elif no_policy_bid:
        status = "No bid"
        status_detail = raw_status
    else:
        status = raw_status
        if policy_bid is not None and current_bid is not None:
            room = policy_bid - current_bid
            if room > 0:
                status_detail = f"Room {_currency_text(room)} to max {_currency_text(policy_bid)}"
            elif room == 0:
                status_detail = f"At max {_currency_text(policy_bid)}"
            else:
                status_detail = f"Over max by {_currency_text(abs(room))}"
        elif policy_bid is not None:
            status_detail = f"Max {_currency_text(policy_bid)}"
        else:
            status_detail = "Max bid unavailable"

    if policy_gate:
        max_label = "No policy bid"
        max_detail = (
            f"Economics {_currency_text(economic_bid)} before {policy_gate.title()} gate"
            if economics_visible
            else f"Blocked by {policy_gate.title()} gate"
        )
    elif policy_bid is None:
        max_label = "N/A"
        max_detail = "No max bid available"
    else:
        max_label = _currency_text(policy_bid)
        if economics_visible and abs((economic_bid or 0.0) - policy_bid) > 1:
            max_detail = f"Policy cap; economics {_currency_text(economic_bid)}"
        elif current_bid is not None and policy_bid > current_bid:
            max_detail = f"Economic cap; room {_currency_text(policy_bid - current_bid)}"
        elif current_bid is not None and policy_bid <= current_bid:
            max_detail = "No room at current bid"
        else:
            max_detail = "Economic cap"

    return {
        "status": status,
        "status_detail": status_detail,
        "max_label": max_label,
        "max_detail": max_detail,
    }


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


def truthy_flag(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def is_safe_verdict(value: Any) -> bool:
    verdict = str(value or "").strip().lower()
    if not verdict:
        return False
    return not any(keyword in verdict for keyword in UNSAFE_VERDICT_KEYWORDS)


def is_safe_opportunity_row(row: pd.Series, *, edge_buffer_default: float = 50.0) -> bool:
    current_price = first_currency_value(
        _first_row_value(row, "current_bid_numeric", "current_bid", "price"),
        _first_row_value(row, "current_bid_numeric_ai", "current_bid_ai", "price_ai"),
    )
    max_bid = first_currency_value(
        _first_row_value(row, "recommended_max_bid", "recommended_max_bid_ai", "max_bid")
    )
    worst_profit = first_currency_value(
        _first_row_value(row, "net_profit_worst", "net_profit_worst_ai", "profit_value")
    )
    verdict = _first_row_value(row, "computed_verdict", "computed_verdict_ai", "verdict", "verdict_ai")
    no_edge = truthy_flag(
        _first_row_value(row, "no_edge", "no_edge_ai", "no_edge_at_current_bid", "no_edge_at_current_bid_ai")
    )
    edge_buffer = first_currency_value(_first_row_value(row, "edge_buffer", "edge_buffer_ai")) or edge_buffer_default

    has_bid_edge = max_bid is not None and max_bid > 0
    if current_price is not None and max_bid is not None:
        has_bid_edge = has_bid_edge and max_bid > current_price + edge_buffer

    return (
        is_safe_verdict(verdict)
        and not no_edge
        and has_bid_edge
        and worst_profit is not None
        and worst_profit > 0
    )


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
        margin = conservative_margin_percent(row)
        confidence_raw = _first_row_value(row, "confidence", "confidence_ai")
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0

        verdict = _first_row_value(row, "computed_verdict", "computed_verdict_ai", "verdict", "verdict_ai")
        is_safe = is_safe_opportunity_row(row)

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
