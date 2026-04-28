from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import ai_listing_valuation
from shared.repair_pricing import RepairAssessment
from shared.top_buy import TopBuyResult


def _base_saved_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "url": "https://example.com/lot/decision-1",
        "year": 2011,
        "make": "Toyota",
        "model": "Corolla",
        "variant": "Ascent",
        "location": "VIC",
        "analysis_timestamp": "2026-04-29T00:00:00+00:00",
        "analysis_context": "active",
        "computed_verdict": "Conditional Flip",
        "verdict": "Conditional Flip",
        "action_label": "Bid carefully",
        "recommended_max_bid": "$4,500",
        "current_bid": "$2,500",
        "current_bid_numeric": 2500,
        "bid_status": "Cheap",
        "repair_estimate": "$1,000",
        "risk_flags": "NO_SERVICE_HISTORY",
    }
    row.update(overrides)
    return row


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


def test_decision_event_payload_captures_meaningful_listing_change() -> None:
    existing = _base_saved_row()
    updated = _base_saved_row(
        analysis_timestamp="2026-04-29T01:00:00+00:00",
        computed_verdict="Marginal (repairs)",
        verdict="Marginal (repairs)",
        action_label="Watch",
        recommended_max_bid="$4,100",
        repair_estimate="$2,250",
        risk_flags="NO_SERVICE_HISTORY|UNREGISTERED",
    )

    event = ai_listing_valuation._decision_event_payload(updated, existing)

    assert event is not None
    assert event["direction"] == "worsened"
    assert event["event_types"] == "verdict_changed|action_changed|max_bid_changed|repair_changed|risk_flags_changed"
    assert "Verdict changed from Conditional Flip to Marginal (repairs)" in event["change_reason_summary"]
    assert "Safe max bid decreased by $400" in event["change_reason_summary"]
    assert "Repair estimate increased by $1,250" in event["change_reason_summary"]
    assert "added UNREGISTERED" in event["change_reason_summary"]


def test_save_result_row_writes_decision_event_only_for_material_change(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ai_results_path = tmp_path / "ai_listing_valuations.csv"
    decision_events_path = tmp_path / "listing_decision_events.csv"
    monkeypatch.setattr(ai_listing_valuation, "AI_RESULTS_PATH", ai_results_path)
    monkeypatch.setattr(ai_listing_valuation, "DECISION_EVENTS_PATH", decision_events_path)
    monkeypatch.setattr(ai_listing_valuation, "_maybe_send_listing_alerts", lambda row, existing_row: None)

    ai_listing_valuation._save_result_row(_base_saved_row())
    assert not decision_events_path.exists()

    ai_listing_valuation._save_result_row(
        _base_saved_row(
            analysis_timestamp="2026-04-29T02:00:00+00:00",
            recommended_max_bid="$4,450",
            current_bid="$2,540",
            current_bid_numeric=2540,
        )
    )
    assert not decision_events_path.exists()

    ai_listing_valuation._save_result_row(
        _base_saved_row(
            analysis_timestamp="2026-04-29T03:00:00+00:00",
            computed_verdict="Marginal (repairs)",
            verdict="Marginal (repairs)",
            action_label="Watch",
            recommended_max_bid="$4,100",
            repair_estimate="$2,250",
            current_bid="$2,900",
            current_bid_numeric=2900,
            bid_status="Near ceiling",
            risk_flags="NO_SERVICE_HISTORY|UNREGISTERED",
        )
    )

    events = pd.read_csv(decision_events_path)
    assert len(events) == 1
    event = events.iloc[0]
    assert event["direction"] == "worsened"
    assert event["previous_verdict"] == "Conditional Flip"
    assert event["new_verdict"] == "Marginal (repairs)"
    assert event["previous_action"] == "Bid carefully"
    assert event["new_action"] == "Watch"
    assert event["event_types"] == (
        "verdict_changed|action_changed|max_bid_changed|repair_changed|risk_flags_changed|bid_status_changed"
    )


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
            "location": "Melbourne VIC",
            "rego_state": "VIC",
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


def test_curve_analysis_keeps_moderate_repairs_as_marginal_not_avoid(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=["COSMETIC_PANEL", "PANEL_REPLACE"],
        cosmetic_panels=2,
        glass_cost=0,
        replacement_cost=850,
        risk_buffer=0,
        base_cost=1500,
        severity_level="moderate",
        severity_multiplier=1.5,
        total_cost=2250,
        reasons=["test repair"],
    )
    listing = pd.Series(
        {
            "url": "test://marginal-repairs",
            "price": "$2,400",
            "make": "Toyota",
            "model": "Corolla",
            "variant": "Ascent",
            "body_type": "Sedan",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "key": "Yes",
            "spare_key": "No",
            "owners_manual": "No",
            "service_history": "No",
            "general_condition": "Moderate cosmetic and light replacement work.",
        }
    )

    monkeypatch.setattr(
        ai_listing_valuation,
        "load_cached_results",
        lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS),
    )
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    assert result["computed_verdict"] == "Marginal (repairs)"
    assert result["action_label"] in {"Watch", "Bid carefully", "Review"}
    assert result["repair_estimate"] == "$2,250"


def test_estimate_costs_uses_roadworthy_not_full_rego_for_unregistered() -> None:
    listing = {
        "body_type": "Hatch",
        "location": "Melbourne VIC",
        "rego_expiry": "Unregistered",
        "rego_no": "",
    }

    costs = ai_listing_valuation._estimate_costs(5_000.0, listing)

    assert costs["rego_estimate"] == 0.0
    assert costs["roadworthy_estimate"] == ai_listing_valuation.ROADWORTHY_ESTIMATE
    assert costs["prep_estimate"] == ai_listing_valuation.DEFAULT_PREP + ai_listing_valuation.DETAILING_HATCH_SEDAN


def test_curve_analysis_uses_current_bid_profit_when_no_edge(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=[],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=0,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=0,
        reasons=[],
    )
    listing = pd.Series(
        {
            "url": "test://no-edge-profit",
            "price": "$5,000",
            "make": "Toyota",
            "model": "Corolla",
            "variant": "Ascent",
            "body_type": "Hatch",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "",
        }
    )

    monkeypatch.setattr(ai_listing_valuation, "load_cached_results", lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS))
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition: repair_assessment)
    monkeypatch.setattr(ai_listing_valuation, "_solve_max_bid", lambda resale_low, min_profit, listing_data: 0.0)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    net_profit_mid = ai_listing_valuation._parse_currency(result["net_profit_mid"])
    impossible_zero_bid_profit = ai_listing_valuation._net_profit_value(20_000, 0.0, listing.to_dict())
    current_bid_profit = ai_listing_valuation._net_profit_value(20_000, 5_000.0, listing.to_dict())

    assert result["recommended_max_bid"] == "$0"
    assert result["no_edge"] is True
    assert net_profit_mid == round(current_bid_profit)
    assert net_profit_mid != round(impossible_zero_bid_profit)


def test_curve_analysis_expected_profit_uses_final_max_bid_basis(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=[],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=0,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=0,
        reasons=[],
    )
    listing = pd.Series(
        {
            "url": "test://expected-profit-max-basis",
            "price": "$5,000",
            "make": "Toyota",
            "model": "Corolla",
            "variant": "Ascent",
            "body_type": "Hatch",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "",
        }
    )

    monkeypatch.setattr(ai_listing_valuation, "load_cached_results", lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS))
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition: repair_assessment)
    monkeypatch.setattr(ai_listing_valuation, "_solve_max_bid", lambda resale_low, min_profit, listing_data: 5_040.0)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    max_bid_profit = ai_listing_valuation._net_profit_value(20_000, 5_040.0, listing.to_dict())
    current_bid_profit = ai_listing_valuation._net_profit_value(20_000, 5_000.0, listing.to_dict())

    assert result["no_edge"] is True
    assert ai_listing_valuation._parse_currency(result["expected_profit"]) == round(max_bid_profit)
    assert ai_listing_valuation._parse_currency(result["expected_profit"]) != round(current_bid_profit)
    assert ai_listing_valuation._parse_currency(result["net_profit_mid"]) == round(current_bid_profit)


def test_curve_analysis_avoids_interstate_listings(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=[],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=0,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=0,
        reasons=[],
    )
    listing = pd.Series(
        {
            "url": "test://interstate",
            "price": "$5,000",
            "make": "Toyota",
            "model": "Corolla",
            "variant": "Ascent",
            "body_type": "Hatch",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "NSW",
            "rego_state": "NSW",
            "general_condition": "",
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

    assert result["recommended_max_bid"] == "$0"
    assert result["expected_profit"] == "$0"
    assert result["net_profit_mid"] == "$0"
    assert result["net_profit_worst"] == "$0"
    assert result["profit_at_current_bid"] == "$0"
    assert result["profit_at_current_bid_worst"] == "$0"
    assert result["current_profit_label"] == "No edge"
    assert result["flip_difficulty"] == "Out of scope"
    assert result["action_label"] == "Avoid"
    assert result["computed_verdict"] == "Avoid"
    assert "INTERSTATE" in result["risk_flags"]


def test_curve_analysis_uses_historical_sold_median_for_expected_auction(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=[],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=0,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=0,
        reasons=[],
    )
    listing = pd.Series(
        {
            "url": "test://historical-auction-price",
            "price": "$2,000",
            "make": "Hyundai",
            "model": "i30",
            "variant": "Active",
            "body_type": "Hatch",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "key": "Yes",
            "spare_key": "Yes",
            "owners_manual": "Yes",
            "service_history": "Full",
            "general_condition": "",
        }
    )

    monkeypatch.setattr(ai_listing_valuation, "load_cached_results", lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS))
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_median=6_200,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    expected_profit = ai_listing_valuation._net_profit_value(20_000, 6_200, listing.to_dict())

    assert result["expected_auction_price"] == "$6,200"
    assert result["expected_auction_source"] == "historical_sold_median"
    assert result["expected_auction_comps_count"] == 5
    assert ai_listing_valuation._parse_currency(result["expected_auction_profit"]) == round(expected_profit)
    assert ai_listing_valuation._parse_currency(result["recommended_max_bid"]) > 6_200
    assert result["current_profit_label"] == "Strong"
    assert result["expected_auction_profit_label"] in {"Good", "Strong"}
    assert result["hard_max_safety"] in {"Conditional", "Strong"}
    assert result["bid_status"] == "Cheap"
    assert result["action_label"] == "Watch"


def test_curve_analysis_uses_worst_case_margin_for_profit_percent(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=[],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=0,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=0,
        reasons=[],
    )
    listing = pd.Series(
        {
            "url": "test://margin-basis",
            "price": "$5,000",
            "make": "Hyundai",
            "model": "i30",
            "variant": "Active",
            "body_type": "Hatch",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "",
        }
    )

    monkeypatch.setattr(
        ai_listing_valuation,
        "load_cached_results",
        lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS),
    )
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    resale_mid = ai_listing_valuation._parse_currency(result["resale_mid"])
    worst_profit = ai_listing_valuation._parse_currency(result["net_profit_worst"])
    mid_profit = ai_listing_valuation._parse_currency(result["net_profit_mid"])
    margin_pct = float(str(result["profit_margin_percent"]).replace("%", ""))

    assert resale_mid is not None and worst_profit is not None and mid_profit is not None
    assert margin_pct == round((worst_profit / resale_mid) * 100.0, 1)
    assert margin_pct != round((mid_profit / resale_mid) * 100.0, 1)


def test_curve_analysis_top_buy_gate_uses_worst_case_margin(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=[],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=0,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=0,
        reasons=[],
    )
    listing = pd.Series(
        {
            "url": "test://top-buy-margin-basis",
            "price": "$5,000",
            "make": "Hyundai",
            "model": "i30",
            "variant": "Active",
            "body_type": "Hatch",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "",
        }
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        ai_listing_valuation,
        "load_cached_results",
        lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS),
    )
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition: repair_assessment)
    monkeypatch.setattr(
        ai_listing_valuation,
        "top_buy_gate_check",
        lambda payload: captured.update(payload) or TopBuyResult(False, ["margin"], []),
    )
    monkeypatch.setattr(
        ai_listing_valuation,
        "apply_top_buy_behavior",
        lambda base_max_bid, top_buy, standard_uncertainty_buffer, top_buy_uncertainty_buffer=0: (base_max_bid, ""),
    )

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    resale_mid = ai_listing_valuation._parse_currency(result["resale_mid"])
    recommended_max_bid = ai_listing_valuation._parse_currency(result["recommended_max_bid"])
    resale_low = ai_listing_valuation._parse_currency(result["resale_low"])
    assert resale_mid is not None and resale_low is not None and recommended_max_bid is not None

    base_costs_map = ai_listing_valuation._estimate_costs(recommended_max_bid, listing.to_dict())
    expected_worst_profit = resale_low - sum(base_costs_map.values()) - recommended_max_bid
    expected_margin = (expected_worst_profit / resale_mid) * 100.0

    assert float(captured["profit_margin_pct"]) == expected_margin


def test_curve_analysis_keeps_raw_expected_finish_and_stores_profit_basis(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=[],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=0,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=0,
        reasons=[],
    )
    listing = pd.Series(
        {
            "url": "test://expected-auction-basis",
            "price": "$8,000",
            "make": "Hyundai",
            "model": "i30",
            "variant": "Active",
            "body_type": "Hatch",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "key": "Yes",
            "spare_key": "Yes",
            "owners_manual": "Yes",
            "service_history": "Full",
            "general_condition": "",
        }
    )

    monkeypatch.setattr(
        ai_listing_valuation,
        "load_cached_results",
        lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS),
    )
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition: repair_assessment)
    monkeypatch.setattr(
        ai_listing_valuation,
        "_expected_auction_estimate",
        lambda resale_mid_val, comps_median=None, comps_count=None: (6_200, "historical_sold_median", 5),
    )

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_median=6_200,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    expected_profit = ai_listing_valuation._net_profit_value(20_000, 8_000, listing.to_dict())

    assert result["expected_auction_price"] == "$6,200"
    assert result["expected_auction_bid_basis"] == "$8,000"
    assert ai_listing_valuation._parse_currency(result["expected_auction_profit"]) == round(expected_profit)


def test_curve_analysis_hard_max_safety_uses_final_max_bid_basis(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=[],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=0,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=0,
        reasons=[],
    )
    listing = pd.Series(
        {
            "url": "test://hard-max-basis",
            "price": "$5,000",
            "make": "Hyundai",
            "model": "i30",
            "variant": "Active",
            "body_type": "Hatch",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "",
        }
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        ai_listing_valuation,
        "load_cached_results",
        lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS),
    )
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition: repair_assessment)
    monkeypatch.setattr(ai_listing_valuation, "_solve_max_bid", lambda resale_low, min_profit, listing_data: 5_040.0)

    def _capture_hard_max_label(profit_value):
        captured["profit_value"] = profit_value
        return "RECORDED"

    monkeypatch.setattr(ai_listing_valuation, "_hard_max_safety_label", _capture_hard_max_label)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    resale_low = ai_listing_valuation._parse_currency(result["resale_low"])
    recommended_max_bid = ai_listing_valuation._parse_currency(result["recommended_max_bid"])
    assert resale_low is not None and recommended_max_bid is not None

    expected_profit_at_max = ai_listing_valuation._net_profit_value(
        resale_low,
        recommended_max_bid,
        listing.to_dict(),
    )

    assert captured["profit_value"] == expected_profit_at_max
    assert result["hard_max_safety"] == "RECORDED"
    assert result["no_edge"] is True
    assert result["action_label"] == "Avoid"


def test_curve_analysis_keeps_repair_estimate_visible_for_hard_avoid(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=True,
        pills=["MECHANICAL"],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=10_000,
        severity_level="major",
        severity_multiplier=1.0,
        total_cost=10_000,
        reasons=["MECHANICAL_REGEX_HIT"],
    )
    listing = pd.Series(
        {
            "url": "test://hard-avoid-repair-estimate",
            "price": "$5,000",
            "make": "Toyota",
            "model": "Camry",
            "variant": "Altise",
            "body_type": "Sedan",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "engine noise observed.",
        }
    )

    monkeypatch.setattr(
        ai_listing_valuation,
        "load_cached_results",
        lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS),
    )
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    assert result["recommended_max_bid"] == "$0"
    assert result["computed_verdict"] == "Avoid"
    assert result["repair_estimate"] == "$10,000"


def test_curve_analysis_surfaces_structural_hard_avoid_bucket(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=True,
        pills=["STRUCTURAL"],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=8_000,
        severity_level="major",
        severity_multiplier=1.0,
        total_cost=8_000,
        reasons=["V2_AVOID: structural_damage: structural damage on chassis rail."],
        hard_avoid_reason="structural",
    )
    listing = pd.Series(
        {
            "url": "test://structural-hard-avoid",
            "price": "$5,000",
            "make": "Toyota",
            "model": "Corolla",
            "variant": "Ascent",
            "body_type": "Sedan",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "structural damage on chassis rail.",
        }
    )

    monkeypatch.setattr(
        ai_listing_valuation,
        "load_cached_results",
        lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS),
    )
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    assert result["recommended_max_bid"] == "$0"
    assert result["computed_verdict"] == "Avoid"
    assert result["repair_estimate"] == "$8,000"
    assert "STRUCTURAL" in result["risk_flags"]


def test_transport_default_matches_local_operating_cost() -> None:
    assert ai_listing_valuation.DEFAULT_TRANSPORT == 200.0
    assert ai_listing_valuation.OPERATING_STATE == "VIC"
    assert ai_listing_valuation._estimate_transport_cost("Melbourne VIC") == 200.0
