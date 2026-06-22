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
    _discounted_resale_cap_price,
    _estimate_costs,
    _expected_auction_estimate,
    _is_interstate_listing,
    _round_to_10,
    _solve_max_bid,
    apply_platform_risk_adjustments,
)
from shared.decision_policy import derive_action_label_from_row
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


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


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
        "action_label": "Review",
    }


def _first_present(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        if text and text.lower() != "nan":
            return value
    return None


def _bid_status_for_replay(
    sold_price: float | None,
    expected_auction_price: float | None,
    max_bid: float | None,
) -> str:
    if sold_price is None:
        return ""
    if max_bid is not None and sold_price > max_bid:
        return "Over max"
    if expected_auction_price is not None and expected_auction_price > 0:
        if sold_price <= expected_auction_price * 0.80:
            return "Cheap"
        if sold_price <= expected_auction_price:
            return "Below expected"
    return "Open"


def _hard_max_safety_for_replay(max_bid: float | None, projected_profit: float | None) -> str:
    if max_bid is None or max_bid <= 0:
        return "No edge"
    if projected_profit is not None and projected_profit >= 3000:
        return "Strong"
    return "Conditional"


def _computed_verdict_for_replay(projected_profit: float | None, *, forced_avoid: bool) -> str:
    if forced_avoid:
        return "Avoid"
    if projected_profit is None:
        return "Review"
    if projected_profit <= 0:
        return "Avoid"
    if projected_profit >= 3000:
        return "Strong Flip"
    return "Conditional Flip"


def classify_miss_reason(row: Mapping[str, Any] | pd.Series) -> str:
    """Bucket a historical replay row into a useful missed-opportunity signal."""
    spec_reason = _clean_text(row.get("spec_reason"))
    if spec_reason:
        return "not covered"

    sold_price = _to_float(row.get("sold_price"))
    max_bid = _to_float(row.get("max_bid"))
    curve_estimate = _to_float(row.get("curve_estimate"))
    curve_high = _to_float(row.get("curve_high"))
    projected_profit = _to_float(row.get("projected_profit_at_sold"))
    delta_pct = _to_float(row.get("delta_pct"))
    risk_buffer = max(_to_float(row.get("risk_buffer")) or 0.0, 0.0)
    repair_cost = max(_to_float(row.get("repair_cost_estimate")) or 0.0, 0.0)
    underbid_pct = _to_float(row.get("underbid_pct"))
    bid_status = _clean_text(row.get("bid_status"))
    hard_max_safety = _clean_text(row.get("hard_max_safety"))
    computed_verdict = _clean_text(row.get("computed_verdict"))
    action_label = _clean_text(row.get("action_label"))
    cost_drag = risk_buffer + repair_cost

    if sold_price is None or curve_estimate is None:
        return "unclassified"

    if max_bid is not None and sold_price > max_bid:
        bid_gap_pct = ((sold_price - max_bid) / max_bid * 100.0) if max_bid > 0 else None
        if bid_gap_pct is not None and bid_gap_pct <= 5.0:
            return "just above max bid"
        if curve_high is not None and sold_price > (curve_high * 1.05):
            return "auction price spike"
        if cost_drag > 0 and (curve_estimate - sold_price) > 0 and cost_drag >= (curve_estimate - sold_price) * 0.35:
            return "risk/cost blocked"
        return "sold above max bid"

    is_buy_miss = action_label == "Buy" or (projected_profit is not None and projected_profit > 0)
    if is_buy_miss:
        if projected_profit is not None and projected_profit >= 10_000:
            return "large-margin buy miss"
        if underbid_pct is not None:
            if underbid_pct >= 20.0:
                return "wide max-bid headroom"
            if underbid_pct >= 10.0:
                return "clear max-bid headroom"
            if underbid_pct <= 5.0:
                return "tight bid window"
        if bid_status == "Cheap":
            return "cheap vs expected auction"
        if bid_status == "Below expected":
            return "below expected auction"
        if computed_verdict == "Strong Flip" or hard_max_safety == "Strong":
            return "strong flip miss"
        return "buy-policy miss"

    if cost_drag > 0:
        return "risk/cost blocked"
    if delta_pct is not None and delta_pct <= 8.0:
        return "thin curve edge"
    return "curve too conservative"


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
    comps_median = _first_present(
        listing_data,
        "comps_median",
        "historical_price_median",
        "expected_auction_median",
    )
    comps_count = _first_present(
        listing_data,
        "comps_count",
        "historical_match_count",
        "expected_auction_comps_count",
    )
    expected_auction_price, _, _ = _expected_auction_estimate(
        resale_mid_val,
        comps_median=comps_median,
        comps_count=comps_count,
    )
    discounted_bid_cap = _discounted_bid_cap(
        _discounted_resale_cap_price(resale_mid_val),
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
    bid_status = ""
    hard_max_safety = "No edge" if max_bid_val == 0.0 else ""
    computed_verdict = "Review"
    action_label = "Review"
    if sold_price is not None:
        costs_map = _estimate_costs(float(sold_price), listing_data)
        platform_fees = float(costs_map.get("fees_estimate", 0.0))
        transport = float(costs_map.get("transport_estimate", 0.0))
        admin_costs = float(costs_map.get("rego_estimate", 0.0)) + float(
            costs_map.get("roadworthy_estimate", 0.0)
        ) + float(
            costs_map.get("prep_estimate", 0.0)
        )
        total_costs = platform_fees + transport + admin_costs + repair_cost + risk_buffer
        projected_profit = resale_mid - sold_price - total_costs
        if resale_mid:
            profit_margin = (projected_profit / resale_mid) * 100
        bid_status = _bid_status_for_replay(sold_price, expected_auction_price, max_bid_val)
        hard_max_safety = _hard_max_safety_for_replay(max_bid_val, projected_profit)
        computed_verdict = _computed_verdict_for_replay(
            projected_profit,
            forced_avoid=bool(max_bid_val == 0.0),
        )
        action_label = derive_action_label_from_row(
            {
                "computed_verdict": computed_verdict,
                "bid_status": bid_status,
                "expected_auction_worst_profit_value": projected_profit,
                "profit_at_current_bid_worst_value": projected_profit,
                "hard_max_safety": hard_max_safety,
            },
            min_profit=MIN_NET_PROFIT_ABSOLUTE,
            fallback="Review",
        )

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
        "bid_status": bid_status,
        "hard_max_safety": hard_max_safety,
        "computed_verdict": computed_verdict,
        "action_label": action_label,
    }
