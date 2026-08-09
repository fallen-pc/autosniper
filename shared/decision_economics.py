"""Shared curve-first economic decision calculations.

Expected auction finish is deliberately not an input to this module. It is a
win-likelihood signal, while the auction-site proxy maximum is determined by
downside resale, ownership costs, repairs, and the required minimum profit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from shared.repair_pricing import RepairAssessment, apply_repairs_to_max_bid


CostEstimator = Callable[[float, Mapping[str, Any]], Mapping[str, float]]
MaxBidSolver = Callable[[float | None, float, Mapping[str, Any]], float]


@dataclass(frozen=True)
class CurveDecisionEconomics:
    proxy_max_bid: float | None
    repair_verdict: str | None
    repair_cost_mid: float
    repair_cost_high: float
    observed_costs: Mapping[str, float]
    observed_profit_mid: float | None
    observed_profit_worst: float | None
    proxy_profit_mid: float | None
    proxy_profit_worst: float | None


def _profit_at_price(
    resale_value: float | None,
    purchase_price: float | None,
    listing: Mapping[str, Any],
    *,
    repair_cost: float,
    estimate_costs: CostEstimator,
) -> float | None:
    if resale_value is None or purchase_price is None:
        return None
    costs = estimate_costs(float(purchase_price), listing)
    return float(resale_value) - float(purchase_price) - sum(float(value) for value in costs.values()) - repair_cost


def calculate_curve_decision_economics(
    listing: Mapping[str, Any],
    *,
    resale_mid: float | None,
    resale_low: float | None,
    observed_price: float | None,
    min_net_profit: float,
    repair_assessment: RepairAssessment,
    solve_max_bid: MaxBidSolver,
    estimate_costs: CostEstimator,
    include_repairs: bool = True,
    policy_blocked: bool = False,
) -> CurveDecisionEconomics:
    """Calculate the shared proxy max and profit bases for live or replay use."""

    repair_cost_mid = float(repair_assessment.total_cost or 0.0) if include_repairs else 0.0
    repair_cost_high = (
        float(repair_assessment.total_cost_high or repair_assessment.total_cost or 0.0)
        if include_repairs
        else 0.0
    )

    proxy_max_bid: float | None = None
    repair_verdict: str | None = None
    if resale_low is not None:
        proxy_max_bid = float(solve_max_bid(resale_low, min_net_profit, listing))
        if include_repairs:
            adjusted_bid, repair_verdict = apply_repairs_to_max_bid(
                int(round(proxy_max_bid)),
                repair_assessment,
                vehicle_value=resale_mid,
            )
            proxy_max_bid = float(adjusted_bid)

    if policy_blocked or (include_repairs and repair_assessment.hard_avoid):
        proxy_max_bid = 0.0

    observed_costs = (
        dict(estimate_costs(float(observed_price), listing))
        if observed_price is not None
        else {}
    )
    observed_profit_mid = _profit_at_price(
        resale_mid,
        observed_price,
        listing,
        repair_cost=repair_cost_mid,
        estimate_costs=estimate_costs,
    )
    observed_profit_worst = _profit_at_price(
        resale_low,
        observed_price,
        listing,
        repair_cost=repair_cost_mid,
        estimate_costs=estimate_costs,
    )
    proxy_profit_mid = _profit_at_price(
        resale_mid,
        proxy_max_bid,
        listing,
        repair_cost=repair_cost_high,
        estimate_costs=estimate_costs,
    )
    proxy_profit_worst = _profit_at_price(
        resale_low,
        proxy_max_bid,
        listing,
        repair_cost=repair_cost_high,
        estimate_costs=estimate_costs,
    )

    if policy_blocked or (include_repairs and repair_assessment.hard_avoid):
        observed_profit_mid = 0.0
        observed_profit_worst = 0.0
        proxy_profit_mid = 0.0
        proxy_profit_worst = 0.0

    return CurveDecisionEconomics(
        proxy_max_bid=proxy_max_bid,
        repair_verdict=repair_verdict,
        repair_cost_mid=repair_cost_mid,
        repair_cost_high=repair_cost_high,
        observed_costs=observed_costs,
        observed_profit_mid=observed_profit_mid,
        observed_profit_worst=observed_profit_worst,
        proxy_profit_mid=proxy_profit_mid,
        proxy_profit_worst=proxy_profit_worst,
    )


def derive_curve_verdict(
    *,
    policy_blocked: bool,
    has_resale_low: bool,
    profit_at_basis_worst: float | None,
    proxy_profit_mid: float | None,
    proxy_profit_worst: float | None,
    no_edge_at_observed_price: bool,
    expected_finish_worst_profit: float | None,
    min_net_profit: float,
    min_expected_profit_viability: float,
) -> str:
    """Resolve the common curve verdict without gating on expected finish.

    Expected-finish weakness changes the explanatory verdict to Marginal but
    remains buyable when the current and proxy-max economics are safe.
    """

    if policy_blocked:
        return "Avoid"
    if not has_resale_low:
        return "Not Covered"
    if profit_at_basis_worst is None or profit_at_basis_worst <= 0:
        return "Avoid"
    if proxy_profit_mid is not None and proxy_profit_mid < min_expected_profit_viability:
        return "Not Viable"
    if no_edge_at_observed_price:
        return "Trap"
    if expected_finish_worst_profit is not None and expected_finish_worst_profit < min_net_profit:
        return "Marginal (expected finish)"
    if proxy_profit_worst is not None and proxy_profit_worst >= 3_000:
        return "Strong Flip"
    return "Conditional Flip"
