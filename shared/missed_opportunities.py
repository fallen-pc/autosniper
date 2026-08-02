"""Decision math for the Missed Opportunities analysis page."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import os
import re

import pandas as pd

from scripts.ai_listing_valuation import (
    EDGE_BUFFER,
    MIN_EXPECTED_PROFIT_VIABILITY,
    MIN_NET_PROFIT_ABSOLUTE,
    MIN_NET_PROFIT_RATIO,
    _interstate_purchase_blocked,
    _calculate_confidence,
    _calculate_downside_percent,
    _detect_risk_flags,
    _bid_status_label,
    _estimate_costs,
    _expected_auction_estimate,
    _hard_max_safety_label,
    _net_profit_value,
    _round_to_10,
    _solve_max_bid,
    apply_platform_risk_adjustments,
)
from shared.comps_engine import parse_currency, parse_numeric
from shared.decision_economics import calculate_curve_decision_economics, derive_curve_verdict
from shared.decision_policy import derive_action_label_from_row
from shared.curves import resolve_curve_canonical_tag
from shared.repair_pricing import assess_repairs, repair_decision_label, vehicle_class_for_listing
from shared.sold_comparables import select_km_aware_comparables

COMPS_STATS_COLUMNS = ["comps_count", "comps_median", "comps_mean", "comps_min", "comps_max"]
COMPS_STATS_INTERNAL_COLUMNS = ["comps_prices", "comps_urls", "comps_odometers"]
EXTERNAL_AUCTION_MATCHES_FILENAME = "external_auction_curve_matches.csv"
EXTERNAL_SETTLED_STATUSES = {"sold", "closed", "ended", "complete", "completed"}


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


def external_auction_matches_path() -> Path:
    output_dir = Path(os.getenv("AUTOSNIPER_EXTERNAL_AUCTIONS_OUTPUT_DIR") or "output/external_auction_scrape/daily")
    return output_dir / EXTERNAL_AUCTION_MATCHES_FILENAME


def _external_settled_date(row: Mapping[str, Any] | pd.Series) -> str:
    date_sold = _clean_text(row.get("date_sold"))
    if date_sold:
        return date_sold
    time_text = _clean_text(row.get("time_remaining_or_date_sold"))
    lower = time_text.lower()
    if not time_text or not any(token in lower for token in ("sold", "closed", "ended", "complete")):
        return ""
    if not re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b", time_text):
        return ""
    return time_text


def load_external_auction_sold_rows(path: Path | None = None) -> pd.DataFrame:
    source_path = path or external_auction_matches_path()
    if not source_path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(source_path, low_memory=False)
    except Exception:
        return pd.DataFrame()
    if df.empty or "url" not in df.columns:
        return pd.DataFrame()

    working = df.copy()
    for column in ("price", "status", "date_sold", "time_remaining_or_date_sold", "canonical_tag", "canonical_reason"):
        if column not in working.columns:
            working[column] = ""
    working["url"] = working["url"].astype(str).str.strip()
    working = working[working["url"].str.startswith("http", na=False)].copy()
    if working.empty:
        return working
    if "source" not in working.columns:
        working["source"] = "external_auction"

    working["price_numeric"] = working["price"].apply(parse_currency)
    working["status_norm"] = working["status"].fillna("").astype(str).str.lower().str.strip()
    working["date_sold"] = working.apply(_external_settled_date, axis=1)
    settled_mask = working["status_norm"].isin(EXTERNAL_SETTLED_STATUSES) | working["date_sold"].astype(str).str.strip().ne("")
    working = working[settled_mask & working["price_numeric"].notna()].copy()
    if working.empty:
        return working.drop(columns=[column for column in ("status_norm",) if column in working.columns])
    working["canonical_tag"] = working["canonical_tag"].fillna("").astype(str).str.strip()
    working["canonical_reason"] = working["canonical_reason"].fillna("").astype(str).str.strip()
    return working.drop(columns=[column for column in ("status_norm",) if column in working.columns])


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


def _parse_odometer_value(value: Any) -> float | None:
    parsed = parse_numeric(value)
    if parsed is not None:
        return float(parsed)
    text = _clean_text(value).lower().replace(",", "").replace("km", "").strip()
    return _to_float(text)


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
    if "odometer_numeric" not in working.columns:
        working["odometer_numeric"] = working.get(
            "odometer_reading", pd.Series(index=working.index)
        ).apply(_parse_odometer_value)
    working["price_numeric"] = pd.to_numeric(working["price_numeric"], errors="coerce")
    working["odometer_numeric"] = pd.to_numeric(working["odometer_numeric"], errors="coerce")
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
            comps_odometers=("odometer_numeric", list),
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
            comps_odometers=("odometer_numeric", list),
        )
    )
    return group_stats, year_stats


def _stats_rows_without_current(stats: pd.Series, current_url: str) -> pd.DataFrame:
    prices = stats.get("comps_prices")
    urls = stats.get("comps_urls")
    odometers = stats.get("comps_odometers")
    if not isinstance(prices, list) or not isinstance(urls, list) or len(prices) != len(urls):
        return pd.DataFrame(columns=["price_numeric", "odometer_numeric", "url"])
    if not isinstance(odometers, list) or len(odometers) != len(prices):
        odometers = [None] * len(prices)
    rows = pd.DataFrame(
        {
            "price_numeric": prices,
            "odometer_numeric": odometers,
            "url": urls,
        }
    )
    if current_url:
        rows = rows[rows["url"].fillna("").astype(str).str.strip() != current_url]
    return rows.reset_index(drop=True)


def historical_comps_for_row(
    row: Mapping[str, Any] | pd.Series,
    *,
    curve_tag: str,
    year_stats: pd.DataFrame,
    group_stats: pd.DataFrame,
) -> dict[str, object]:
    """Return live-style sold-comps context for a replay row."""

    pool = pd.DataFrame()
    year_val = _to_int(row.get("year"))
    current_url = str(row.get("url") or "").strip()
    if year_val is not None and not year_stats.empty and (curve_tag, year_val) in year_stats.index:
        year_candidate = year_stats.loc[(curve_tag, year_val)]
        year_pool = _stats_rows_without_current(year_candidate, current_url)
        if len(year_pool) >= 3:
            pool = year_pool
    if pool.empty and curve_tag and not group_stats.empty and curve_tag in group_stats.index:
        group_candidate = group_stats.loc[curve_tag]
        pool = _stats_rows_without_current(group_candidate, current_url)
    if pool.empty:
        return {
            "historical_match_count": 0,
            "historical_price_median": None,
            "comps_count": 0,
            "comps_median": None,
            "comps_method": "none",
        }
    target_km = _to_float(
        row.get("odometer_numeric")
        if row.get("odometer_numeric") is not None
        else _parse_odometer_value(row.get("odometer_reading"))
    )
    _, stats = select_km_aware_comparables(pool, target_km)
    return {
        "historical_match_count": stats.count,
        "historical_price_median": stats.median,
        "comps_count": stats.count,
        "comps_median": stats.median,
        "comps_method": stats.method,
        "comps_km_min": stats.km_min,
        "comps_km_max": stats.km_max,
        "comps_km_distance_median": stats.km_distance_median,
    }


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
    That path mirrors the curve-first AI Analysis decision: solve the downside
    resale proxy max, apply repair deductions, and keep expected auction finish
    as informational win-likelihood context rather than a second bid cap.
    """
    if resale_mid is None or resale_mid <= 0:
        return _blank_decision()

    listing_data = dict(row)
    resale_mid_val = _round_to_10(resale_mid)
    repair_assessment = assess_repairs(
        listing_data.get("general_condition", ""),
        vehicle_value=resale_mid,
        vehicle_class=vehicle_class_for_listing(listing_data),
    )
    unresolved_repair_items = sorted(
        {
            str(getattr(fragment, "original_text", "")).strip().rstrip(".")
            for fragment in (getattr(repair_assessment, "fragments", None) or [])
            if str(getattr(fragment, "status", "")).strip().lower() == "unclassified"
            and str(getattr(fragment, "original_text", "")).strip()
        }
    )
    risk_flags = _detect_risk_flags(listing_data)
    if unresolved_repair_items and "UNRESOLVED_REPAIRS" not in risk_flags:
        risk_flags.append("UNRESOLVED_REPAIRS")
    if repair_assessment.pricing_class_uncertain and "REPAIR_PRICING_CLASS_UNCERTAIN" not in risk_flags:
        risk_flags.append("REPAIR_PRICING_CLASS_UNCERTAIN")
    downside_pct = _calculate_downside_percent(risk_flags)
    confidence_result = _calculate_confidence(
        listing_data,
        risk_flags,
        resale_mid=resale_mid_val,
        repair_assessment=repair_assessment,
    )
    confidence_val, notes = confidence_result
    downside_pct, confidence_val, risk_flags, notes = apply_platform_risk_adjustments(
        listing_data, downside_pct, confidence_val, risk_flags, notes
    )
    resale_low_val = _round_to_10(resale_mid * (1.0 - downside_pct))
    min_net_profit = max(MIN_NET_PROFIT_ABSOLUTE, MIN_NET_PROFIT_RATIO * (resale_low_val or resale_mid))
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
    # Exposed so callers (e.g. the Missed Opportunities table) can show the same
    # vehicle-value-scaled Good/Marginal/Not Viable/Avoid label this function used
    # internally, instead of separately recomputing it against flat dollar gates.
    repair_decision = repair_decision_label(repair_assessment, vehicle_value=resale_mid_val or resale_mid)
    sold_price = _to_float(listing_data.get("price_numeric"))
    economics = calculate_curve_decision_economics(
        listing_data,
        resale_mid=resale_mid_val,
        resale_low=resale_low_val,
        observed_price=sold_price,
        min_net_profit=min_net_profit,
        repair_assessment=repair_assessment,
        solve_max_bid=_solve_max_bid,
        estimate_costs=_estimate_costs,
        include_repairs=include_repairs,
        policy_blocked=_interstate_purchase_blocked(listing_data),
    )
    max_bid_val = economics.proxy_max_bid
    repair_cost_total = economics.repair_cost_mid
    risk_buffer = float(repair_assessment.risk_buffer or 0.0) if include_repairs else 0.0
    repair_cost = max(0.0, repair_cost_total - risk_buffer)
    platform_fees = transport = admin_costs = total_costs = None
    projected_profit = None
    projected_profit_worst = None
    profit_margin = None
    bid_status = ""
    hard_max_safety = "No edge" if max_bid_val == 0.0 else ""
    computed_verdict = "Review"
    action_label = "Review"
    if sold_price is not None:
        costs_map = economics.observed_costs
        platform_fees = float(costs_map.get("fees_estimate", 0.0))
        transport = float(costs_map.get("transport_estimate", 0.0))
        admin_costs = float(costs_map.get("rego_estimate", 0.0)) + float(
            costs_map.get("roadworthy_estimate", 0.0)
        ) + float(
            costs_map.get("prep_estimate", 0.0)
        )
        total_costs = platform_fees + transport + admin_costs + repair_cost + risk_buffer
        projected_profit = economics.observed_profit_mid
        projected_profit_worst = economics.observed_profit_worst
        if resale_mid:
            profit_margin = (projected_profit / resale_mid) * 100
        bid_status = _bid_status_label(sold_price, expected_auction_price, max_bid_val)
        hard_max_safety = _hard_max_safety_label(economics.proxy_profit_worst)
        no_edge_at_sold = max_bid_val is not None and max_bid_val <= sold_price + EDGE_BUFFER
        profit_at_basis_worst = projected_profit_worst if no_edge_at_sold else economics.proxy_profit_worst
        expected_basis = max(sold_price, expected_auction_price) if expected_auction_price is not None else None
        expected_worst_profit = (
            _net_profit_value(resale_low_val or resale_mid, expected_basis, listing_data) - repair_cost_total
            if expected_basis is not None
            else None
        )
        computed_verdict = derive_curve_verdict(
            policy_blocked=_interstate_purchase_blocked(listing_data),
            has_resale_low=resale_low_val is not None,
            profit_at_basis_worst=profit_at_basis_worst,
            proxy_profit_mid=economics.proxy_profit_mid,
            proxy_profit_worst=economics.proxy_profit_worst,
            no_edge_at_observed_price=no_edge_at_sold,
            expected_finish_worst_profit=expected_worst_profit,
            min_net_profit=MIN_NET_PROFIT_ABSOLUTE,
            min_expected_profit_viability=MIN_EXPECTED_PROFIT_VIABILITY,
        )
        if include_repairs and repair_assessment.hard_avoid:
            computed_verdict = "Avoid"
        elif economics.repair_verdict in {"Avoid", "Not Viable"}:
            computed_verdict = "Avoid"
        elif economics.repair_verdict == "Marginal" and computed_verdict not in {"Avoid", "Trap", "Not Viable"}:
            computed_verdict = "Marginal (repairs)"
        action_label = derive_action_label_from_row(
            {
                "computed_verdict": computed_verdict,
                "bid_status": bid_status,
                "expected_auction_worst_profit_value": expected_worst_profit,
                "profit_at_current_bid_worst_value": projected_profit_worst,
                "hard_max_safety": hard_max_safety,
                "expected_auction_comps_count": comps_count,
            },
            min_profit=MIN_NET_PROFIT_ABSOLUTE,
            fallback="Review",
        )
        if unresolved_repair_items and action_label != "Avoid":
            computed_verdict = "Review (unresolved repairs)"
            action_label = "Review"
        elif repair_assessment.pricing_class_uncertain and action_label != "Avoid":
            computed_verdict = "Review (repair pricing evidence)"
            action_label = "Review"

    return {
        "max_bid": max_bid_val,
        "projected_profit_at_sold": projected_profit,
        "projected_profit_worst_at_sold": projected_profit_worst if sold_price is not None else None,
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
        "unresolved_repair_count": len(unresolved_repair_items),
        "unresolved_repairs": " | ".join(unresolved_repair_items),
        "repair_pricing_vehicle_class": repair_assessment.pricing_vehicle_class,
        "repair_pricing_class_uncertain": repair_assessment.pricing_class_uncertain,
        "repair_pricing_incompatible_canonicals": "|".join(
            repair_assessment.pricing_incompatible_canonicals
        ),
    }
