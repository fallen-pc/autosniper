"""Decision math for the Missed Opportunities analysis page."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from scripts.ai_listing_valuation import (
    MIN_NET_PROFIT_ABSOLUTE,
    MIN_NET_PROFIT_RATIO,
    _interstate_purchase_blocked,
    _calculate_confidence,
    _calculate_downside_percent,
    _detect_risk_flags,
    _discounted_bid_cap,
    _discounted_resale_cap_price,
    _estimate_costs,
    _expected_auction_estimate,
    _round_to_10,
    _solve_max_bid,
    apply_platform_risk_adjustments,
)
from shared.comps_engine import parse_currency
from shared.decision_policy import derive_action_label_from_row
from shared.curves import resolve_curve_canonical_tag
from shared.repair_pricing import assess_repairs, apply_repairs_to_max_bid, repair_decision_label

# Profit threshold that upgrades a replay verdict from "Conditional Flip" to "Strong Flip".
# Distinct from MIN_NET_PROFIT_ABSOLUTE (the minimum required for any BUY decision).
STRONG_FLIP_PROFIT_THRESHOLD = 3_000

COMPS_STATS_COLUMNS = ["comps_count", "comps_median", "comps_mean", "comps_min", "comps_max"]
COMPS_STATS_INTERNAL_COLUMNS = ["comps_prices", "comps_urls"]


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
        "repair_decision": None,
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


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _empty_comps_stats() -> pd.DataFrame:
    return pd.DataFrame(columns=COMPS_STATS_COLUMNS + COMPS_STATS_INTERNAL_COLUMNS)


def build_historical_comps_stats(sold_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the same curve-tag/year sold-comps tables used by live AI Analysis."""

    if sold_df.empty or "canonical_tag" not in sold_df.columns:
        empty_group = _empty_comps_stats()
        empty_year = _empty_comps_stats()
        return empty_group, empty_year

    working = sold_df.copy()
    working["curve_tag"] = working["canonical_tag"].apply(resolve_curve_canonical_tag)
    if "year_int" not in working.columns:
        working["year_int"] = working.get("year", pd.Series(index=working.index)).apply(_to_int)
    if "price_numeric" not in working.columns:
        working["price_numeric"] = working.get("price", pd.Series(index=working.index)).apply(parse_currency)
    working["price_numeric"] = pd.to_numeric(working["price_numeric"], errors="coerce")
    valid = working.dropna(subset=["curve_tag", "price_numeric"]).copy()
    valid = valid[valid["price_numeric"] > 0]
    if "url" in valid.columns:
        valid["comps_url"] = valid["url"].fillna("").astype(str).str.strip()
    else:
        valid["comps_url"] = ""

    if valid.empty:
        empty_group = _empty_comps_stats()
        empty_year = _empty_comps_stats()
        return empty_group, empty_year

    group_stats = (
        valid.groupby("curve_tag")
        .agg(
            comps_count=("price_numeric", "count"),
            comps_median=("price_numeric", "median"),
            comps_mean=("price_numeric", "mean"),
            comps_min=("price_numeric", "min"),
            comps_max=("price_numeric", "max"),
            comps_prices=("price_numeric", list),
            comps_urls=("comps_url", list),
        )
    )
    year_stats = (
        valid.dropna(subset=["year_int"])
        .groupby(["curve_tag", "year_int"])
        .agg(
            comps_count=("price_numeric", "count"),
            comps_median=("price_numeric", "median"),
            comps_mean=("price_numeric", "mean"),
            comps_min=("price_numeric", "min"),
            comps_max=("price_numeric", "max"),
            comps_prices=("price_numeric", list),
            comps_urls=("comps_url", list),
        )
    )
    return group_stats, year_stats


def _stats_count_median_without_current(stats: pd.Series, current_url: str) -> tuple[int, float | None]:
    prices = stats.get("comps_prices")
    urls = stats.get("comps_urls")
    if isinstance(prices, list) and isinstance(urls, list) and len(prices) == len(urls) and current_url:
        filtered_prices = [
            _to_float(price)
            for price, url in zip(prices, urls)
            if str(url or "").strip() != current_url
        ]
        valid_prices = [price for price in filtered_prices if price is not None and price > 0]
        if not valid_prices:
            return 0, None
        return len(valid_prices), float(pd.Series(valid_prices).median())
    return _to_int(stats.get("comps_count")) or 0, _to_float(stats.get("comps_median"))


def historical_comps_for_row(
    row: Mapping[str, Any] | pd.Series,
    *,
    curve_tag: str,
    year_stats: pd.DataFrame,
    group_stats: pd.DataFrame,
) -> dict[str, object]:
    """Return live-style sold-comps context for a replay row."""

    stats = None
    year_val = _to_int(row.get("year"))
    current_url = str(row.get("url") or "").strip()
    if year_val is not None and not year_stats.empty and (curve_tag, year_val) in year_stats.index:
        year_candidate = year_stats.loc[(curve_tag, year_val)]
        if _stats_count_median_without_current(year_candidate, current_url)[0] > 0:
            stats = year_candidate
    if stats is None and curve_tag and not group_stats.empty and curve_tag in group_stats.index:
        group_candidate = group_stats.loc[curve_tag]
        if _stats_count_median_without_current(group_candidate, current_url)[0] > 0:
            stats = group_candidate
    if stats is None:
        return {
            "historical_match_count": 0,
            "historical_price_median": None,
            "comps_count": 0,
            "comps_median": None,
        }
    count, median = _stats_count_median_without_current(stats, current_url)
    return {
        "historical_match_count": count,
        "historical_price_median": median,
        "comps_count": count,
        "comps_median": median,
    }


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
    if projected_profit is not None and projected_profit >= STRONG_FLIP_PROFIT_THRESHOLD:
        return "Strong"
    return "Conditional"


def _computed_verdict_for_replay(projected_profit: float | None, *, forced_avoid: bool) -> str:
    if forced_avoid:
        return "Avoid"
    if projected_profit is None:
        return "Review"
    if projected_profit <= 0:
        return "Avoid"
    if projected_profit >= STRONG_FLIP_PROFIT_THRESHOLD:
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

    repair_assessment = assess_repairs(
        listing_data.get("general_condition", ""), vehicle_value=resale_mid_val or resale_mid
    )
    # Exposed so callers (e.g. the Missed Opportunities table) can show the same
    # vehicle-value-scaled Good/Marginal/Not Viable/Avoid label this function used
    # internally, instead of separately recomputing it against flat dollar gates.
    repair_decision = repair_decision_label(repair_assessment, vehicle_value=resale_mid_val or resale_mid)
    repair_cost_total = float(repair_assessment.total_cost or 0.0) if include_repairs else 0.0
    risk_buffer = float(repair_assessment.risk_buffer or 0.0) if include_repairs else 0.0
    repair_cost = max(0.0, repair_cost_total - risk_buffer)

    if include_repairs and max_bid_val is not None:
        adjusted_bid, _ = apply_repairs_to_max_bid(
            int(round(max_bid_val)),
            repair_assessment,
            vehicle_value=resale_mid_val or resale_mid,
        )
        max_bid_val = float(adjusted_bid)
    if include_repairs and repair_assessment.hard_avoid:
        max_bid_val = 0.0
    if _interstate_purchase_blocked(listing_data):
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
                "expected_auction_comps_count": comps_count,
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
        "repair_decision": repair_decision,
        "expected_auction_price": expected_auction_price,
        "bid_status": bid_status,
        "hard_max_safety": hard_max_safety,
        "computed_verdict": computed_verdict,
        "action_label": action_label,
    }
