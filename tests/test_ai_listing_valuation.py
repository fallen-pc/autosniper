from __future__ import annotations

import pandas as pd

from scripts import ai_listing_valuation
from shared.repair_pricing import RepairAssessment


def test_price_change_metadata_records_increase() -> None:
    row = {
        "url": "https://example.com/lot/1",
        "current_bid": "$10,500",
        "current_bid_numeric": 10500,
    }
    existing = {
        "url": "https://example.com/lot/1",
        "current_bid": "$10,000",
        "current_bid_numeric": 10000,
    }

    result = ai_listing_valuation._with_price_change_metadata(
        row,
        existing,
        changed_at="2026-04-11T09:00:00+00:00",
    )

    assert result["previous_current_bid"] == "$10,000"
    assert result["previous_current_bid_numeric"] == 10000
    assert result["price_change_delta"] == 500
    assert result["price_change_direction"] == "increased"
    assert result["price_changed_at"] == "2026-04-11T09:00:00+00:00"


def test_price_change_metadata_preserves_existing_change_when_price_same() -> None:
    row = {
        "url": "https://example.com/lot/1",
        "current_bid": "$10,500",
        "current_bid_numeric": 10500,
    }
    existing = {
        "url": "https://example.com/lot/1",
        "current_bid": "$10,500",
        "current_bid_numeric": 10500,
        "previous_current_bid": "$10,000",
        "previous_current_bid_numeric": 10000,
        "price_change_delta": 500,
        "price_change_direction": "increased",
        "price_changed_at": "2026-04-11T09:00:00+00:00",
    }

    result = ai_listing_valuation._with_price_change_metadata(row, existing)

    assert result["price_change_delta"] == 500
    assert result["price_change_direction"] == "increased"
    assert result["price_changed_at"] == "2026-04-11T09:00:00+00:00"


def test_curve_analysis_subtracts_repair_cost_from_displayed_profit(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=["COSMETIC_PANEL"],
        cosmetic_panels=1,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=1000,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=1000,
        reasons=["test repair"],
    )
    listing = pd.Series(
        {
            "url": "test://repair-profit",
            "price": "$5,000",
            "make": "Toyota",
            "model": "Corolla",
            "variant": "Ascent",
            "body_type": "Hatch",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Sydney NSW",
            "rego_state": "NSW",
            "general_condition": "Cosmetic test damage.",
        }
    )

    monkeypatch.setattr(ai_listing_valuation, "load_cached_results", lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS))
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    max_bid = ai_listing_valuation._parse_currency(result["recommended_max_bid"])
    net_profit_mid = ai_listing_valuation._parse_currency(result["net_profit_mid"])
    expected_profit_without_repair = ai_listing_valuation._net_profit_value(
        20_000,
        max_bid,
        listing.to_dict(),
    )

    assert result["repair_estimate"] == "$1,000"
    assert net_profit_mid == round(expected_profit_without_repair - 1000)
