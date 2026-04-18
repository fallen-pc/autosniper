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
            "location": "Sydney NSW",
            "rego_state": "NSW",
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
    assert result["projected_profit_at_sold"] == 6201


def test_missed_decision_metrics_can_run_no_repair_hypothesis(monkeypatch) -> None:
    row = pd.Series(
        {
            "url": "test://missed",
            "price_numeric": 10_000,
            "price": "$10,000",
            "body_type": "Hatch",
            "location": "Sydney NSW",
            "rego_state": "NSW",
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
    assert result["projected_profit_at_sold"] == 7201
