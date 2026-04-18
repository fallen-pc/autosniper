"""Decision math for the Missed Opportunities analysis page."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from scripts.ai_listing_valuation import (
    MIN_NET_PROFIT_ABSOLUTE,
    MIN_NET_PROFIT_RATIO,
    INTERSTATE_BUYING_ALLOWED,
    _calculate_confidence,
    _calculate_downside_percent,
    _detect_risk_flags,
    _discounted_bid_cap,
    _estimate_costs,
    _expected_auction_price,
    _is_interstate_listing,
    _round_to_10,
    _solve_max_bid,
    apply_platform_risk_adjustments,
)
from shared.repair_pricing import assess_repairs, apply_repairs_to_max_bid


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _blank_decision() -> dict[str, object]:
    return {
        "max_bid": None,
        "projected_profit_at_sold": None,
        "profit_margin_pct": None,
        "total_costs": None,
        "platform_fees": None,
        "transport": None,
        "admin_costs": None,
        "risk_buffer": None,
        "repair_cost": None,
        "expected_auction_price": None,
    }


def compute_decision_metrics(
    row: Mapping[str, Any] | pd.Series,
    resale_mid: float | None,
    *,
    include_repairs: bool,
) -> dict[str, object]:
    """Rebuild the live AI buy/no-buy math for a historical sold listing.

    The default Missed Opportunities view uses this with ``include_repairs=True``.
    That path mirrors the curve-first AI Analysis decision: solve the worst-case
    max bid, apply the expected-auction cap, then apply repair deductions.
    """
    if resale_mid is None or resale_mid <= 0:
        return _blank_decision()

    listing_data = dict(row)
    risk_flags = _detect_risk_flags(listing_data)
    downside_pct = _calculate_downside_percent(risk_flags)
    confidence_val = _calculate_confidence(listing_data, risk_flags)
    notes: list[str] = []
    downside_pct, confidence_val, risk_flags, notes = apply_platform_risk_adjustments(
        listing_data,
        downside_pct,
        confidence_val,
        risk_flags,
        notes,
    )

    resale_mid_val = _round_to_10(resale_mid)
    resale_low_val = _round_to_10(resale_mid * (1.0 - downside_pct))
    min_net_profit = max(
        MIN_NET_PROFIT_ABSOLUTE,
        MIN_NET_PROFIT_RATIO * (resale_low_val or resale_mid),
    )
    max_bid_val = _solve_max_bid(resale_low_val, min_net_profit, listing_data)
    expected_auction_price = _expected_auction_price(resale_mid_val)
    discounted_bid_cap = _discounted_bid_cap(
        expected_auction_price,
        repair_cost=0.0,
        margin=min_net_profit,
    )
    if discounted_bid_cap is not None and max_bid_val is not None:
        max_bid_val = min(max_bid_val, discounted_bid_cap)
    elif discounted_bid_cap is not None:
        max_bid_val = discounted_bid_cap

    repair_assessment = assess_repairs(listing_data.get("general_condition", ""))
    repair_cost_total = float(repair_assessment.total_cost or 0.0) if include_repairs else 0.0
    risk_buffer = float(repair_assessment.risk_buffer or 0.0) if include_repairs else 0.0
    repair_cost = max(0.0, repair_cost_total - risk_buffer)

    if include_repairs and max_bid_val is not None:
        adjusted_bid, _ = apply_repairs_to_max_bid(
            int(round(max_bid_val)),
            repair_assessment,
        )
        max_bid_val = float(adjusted_bid)
    if include_repairs and repair_assessment.hard_avoid:
        max_bid_val = 0.0
    if _is_interstate_listing(listing_data) and not INTERSTATE_BUYING_ALLOWED:
        max_bid_val = 0.0

    sold_price = _to_float(listing_data.get("price_numeric"))
    platform_fees = transport = admin_costs = total_costs = None
    projected_profit = None
    profit_margin = None
    if sold_price is not None:
        costs_map = _estimate_costs(float(sold_price), listing_data)
        platform_fees = float(costs_map.get("fees_estimate", 0.0))
        transport = float(costs_map.get("transport_estimate", 0.0))
        admin_costs = float(costs_map.get("rego_estimate", 0.0)) + float(
            costs_map.get("prep_estimate", 0.0)
        )
        total_costs = platform_fees + transport + admin_costs + repair_cost + risk_buffer
        projected_profit = resale_mid - sold_price - total_costs
        if resale_mid:
            profit_margin = (projected_profit / resale_mid) * 100

    return {
        "max_bid": max_bid_val,
        "projected_profit_at_sold": projected_profit,
        "profit_margin_pct": profit_margin,
        "total_costs": total_costs,
        "platform_fees": platform_fees,
        "transport": transport,
        "admin_costs": admin_costs,
        "risk_buffer": risk_buffer,
        "repair_cost": repair_cost,
        "expected_auction_price": expected_auction_price,
    }
