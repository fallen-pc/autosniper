from __future__ import annotations

import pandas as pd

from shared import missed_opportunities
from shared.repair_pricing import RepairAssessment


def _repair_assessment(total_cost: int = 1000, risk_buffer: int = 300) -> RepairAssessment:
    return RepairAssessment(
        hard_avoid=False,
        pills=["COSMETIC_PANEL", "UNKNOWN"],
        cosmetic_panels=1,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=risk_buffer,
        base_cost=total_cost,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=total_cost,
        reasons=["test"],
    )


def test_missed_decision_metrics_apply_ai_cap_and_repair_cost(monkeypatch) -> None:
    row = pd.Series(
        {
            "url": "test://missed",
            "price_numeric": 10_000,
            "price": "$10,000",
            "body_type": "Hatch",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "Cosmetic damage. Please refer to photos.",
        }
    )

    monkeypatch.setattr(missed_opportunities, "_solve_max_bid", lambda resale_low, min_profit, listing: 20_000)
    monkeypatch.setattr(missed_opportunities, "assess_repairs", lambda condition: _repair_assessment())

    result = missed_opportunities.compute_decision_metrics(
        row,
        20_000,
        include_repairs=True,
    )

    assert result["expected_auction_price"] == 15_000
    assert result["max_bid"] == 11_780
    assert result["repair_cost"] == 700
    assert result["risk_buffer"] == 300
    assert result["projected_profit_at_sold"] == 7351


def test_missed_decision_metrics_can_run_no_repair_hypothesis(monkeypatch) -> None:
    row = pd.Series(
        {
            "url": "test://missed",
            "price_numeric": 10_000,
            "price": "$10,000",
            "body_type": "Hatch",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "Cosmetic damage. Please refer to photos.",
        }
    )

    monkeypatch.setattr(missed_opportunities, "_solve_max_bid", lambda resale_low, min_profit, listing: 20_000)
    monkeypatch.setattr(missed_opportunities, "assess_repairs", lambda condition: _repair_assessment())

    result = missed_opportunities.compute_decision_metrics(
        row,
        20_000,
        include_repairs=False,
    )

    assert result["max_bid"] == 12_780
    assert result["repair_cost"] == 0
    assert result["risk_buffer"] == 0
    assert result["projected_profit_at_sold"] == 8351


def test_missed_decision_metrics_zeroes_interstate_max_bid(monkeypatch) -> None:
    row = pd.Series(
        {
            "url": "test://missed-interstate",
            "price_numeric": 10_000,
            "price": "$10,000",
            "body_type": "Hatch",
            "location": "NSW",
            "rego_state": "NSW",
            "general_condition": "",
        }
    )

    monkeypatch.setattr(missed_opportunities, "_solve_max_bid", lambda resale_low, min_profit, listing: 20_000)
    monkeypatch.setattr(missed_opportunities, "assess_repairs", lambda condition: _repair_assessment(total_cost=0, risk_buffer=0))

    result = missed_opportunities.compute_decision_metrics(
        row,
        20_000,
        include_repairs=True,
    )

    assert result["max_bid"] == 0.0


def test_missed_decision_metrics_keeps_historical_median_context_without_capping_max_bid(monkeypatch) -> None:
    row = pd.Series(
        {
            "url": "test://missed-historical-cap",
            "price_numeric": 10_000,
            "price": "$10,000",
            "body_type": "Hatch",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "",
            "historical_price_median": 12_300,
            "historical_match_count": 5,
        }
    )

    monkeypatch.setattr(missed_opportunities, "_solve_max_bid", lambda resale_low, min_profit, listing: 20_000)
    monkeypatch.setattr(
        missed_opportunities,
        "assess_repairs",
        lambda condition: _repair_assessment(total_cost=0, risk_buffer=0),
    )

    result = missed_opportunities.compute_decision_metrics(
        row,
        20_000,
        include_repairs=True,
    )

    assert result["expected_auction_price"] == 12_300
    assert result["max_bid"] == 12_780


def test_missed_decision_metrics_uses_shared_buy_policy(monkeypatch) -> None:
    row = pd.Series(
        {
            "url": "test://missed-shared-buy",
            "price_numeric": 10_000,
            "price": "$10,000",
            "body_type": "Hatch",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "",
        }
    )

    monkeypatch.setattr(missed_opportunities, "_solve_max_bid", lambda resale_low, min_profit, listing: 20_000)
    monkeypatch.setattr(
        missed_opportunities,
        "assess_repairs",
        lambda condition: _repair_assessment(total_cost=0, risk_buffer=0),
    )

    result = missed_opportunities.compute_decision_metrics(
        row,
        20_000,
        include_repairs=True,
    )

    assert result["computed_verdict"] == "Strong Flip"
    assert result["bid_status"] == "Cheap"
    assert result["hard_max_safety"] == "Strong"
    assert result["action_label"] == "Buy"


def test_missed_decision_metrics_uses_shared_over_max_avoid_policy(monkeypatch) -> None:
    row = pd.Series(
        {
            "url": "test://missed-over-max",
            "price_numeric": 13_000,
            "price": "$13,000",
            "body_type": "Hatch",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "",
        }
    )

    monkeypatch.setattr(missed_opportunities, "_solve_max_bid", lambda resale_low, min_profit, listing: 20_000)
    monkeypatch.setattr(
        missed_opportunities,
        "assess_repairs",
        lambda condition: _repair_assessment(total_cost=0, risk_buffer=0),
    )

    result = missed_opportunities.compute_decision_metrics(
        row,
        20_000,
        include_repairs=True,
    )

    assert result["max_bid"] == 12_780
    assert result["bid_status"] == "Over max"
    assert result["action_label"] == "Avoid"


def test_classify_miss_reason_splits_buy_miss_headroom() -> None:
    row = pd.Series(
        {
            "sold_price": 8_000,
            "max_bid": 12_000,
            "curve_estimate": 18_000,
            "projected_profit_at_sold": 8_500,
            "underbid_pct": 33.3,
            "action_label": "Buy",
            "bid_status": "Cheap",
            "hard_max_safety": "Strong",
            "computed_verdict": "Strong Flip",
        }
    )

    assert missed_opportunities.classify_miss_reason(row) == "wide max-bid headroom"


def test_classify_miss_reason_flags_large_margin_before_headroom() -> None:
    row = pd.Series(
        {
            "sold_price": 8_000,
            "max_bid": 12_000,
            "curve_estimate": 23_000,
            "projected_profit_at_sold": 12_500,
            "underbid_pct": 33.3,
            "action_label": "Buy",
            "bid_status": "Cheap",
            "hard_max_safety": "Strong",
            "computed_verdict": "Strong Flip",
        }
    )

    assert missed_opportunities.classify_miss_reason(row) == "large-margin buy miss"


def test_classify_miss_reason_splits_over_max_from_price_spike() -> None:
    row = pd.Series(
        {
            "sold_price": 13_000,
            "max_bid": 12_000,
            "curve_estimate": 18_000,
            "curve_high": 19_000,
            "projected_profit_at_sold": 2_000,
            "action_label": "Avoid",
            "bid_status": "Over max",
        }
    )

    assert missed_opportunities.classify_miss_reason(row) == "sold above max bid"
