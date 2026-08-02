from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import ai_listing_valuation
from shared.repair_pricing import RepairAssessment, RepairFragment


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


def _set_alert_dataset_paths(monkeypatch, tmp_path: Path, *, active: bool = True, sold: bool = False, referred: bool = False) -> None:
    url = str(_base_saved_row()["url"])
    active_path = tmp_path / "active_vehicle_details.csv"
    sold_path = tmp_path / "sold_cars.csv"
    referred_path = tmp_path / "referred_cars.csv"
    pd.DataFrame({"url": [url] if active else []}).to_csv(active_path, index=False)
    pd.DataFrame({"url": [url] if sold else []}).to_csv(sold_path, index=False)
    pd.DataFrame({"url": [url] if referred else []}).to_csv(referred_path, index=False)
    monkeypatch.setattr(ai_listing_valuation, "ACTIVE_LISTINGS_PATH", active_path)
    monkeypatch.setattr(ai_listing_valuation, "SOLD_LISTINGS_PATH", sold_path)
    monkeypatch.setattr(ai_listing_valuation, "REFERRED_LISTINGS_PATH", referred_path)


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


def test_listing_alert_reports_ai_analysis_buy_action(monkeypatch, tmp_path: Path) -> None:
    _set_alert_dataset_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTOSNIPER_AI_ANALYSIS_URL", "https://autosniper.example/AI_ANALYSIS")
    sent: list[dict[str, object]] = []

    def fake_send_on_state_change(alert_scope, url, state_value, message, verdict=None):
        sent.append(
            {
                "alert_scope": alert_scope,
                "url": url,
                "state_value": state_value,
                "message": message,
                "verdict": verdict,
            }
        )
        return True

    monkeypatch.setattr(ai_listing_valuation, "send_on_state_change", fake_send_on_state_change)

    ai_listing_valuation._maybe_send_listing_alerts(
        _base_saved_row(action_label="Buy", bid_status="Cheap"),
        None,
    )

    assert len(sent) == 1
    assert sent[0]["alert_scope"] == "listing_bid_ready"
    assert sent[0]["state_value"] == "ai_analysis_buy"
    assert "$$$ POTENTIAL BUY ALERT $$$" in str(sent[0]["message"])
    assert "Alert type: AI Analysis Buy candidate" in str(sent[0]["message"])
    assert "DEAL NUMBERS\nCurrent bid: $2,500\nProxy max bid: $4,500" in str(sent[0]["message"])
    assert "Why sent: this current active listing is marked Buy in AI Analysis." in str(sent[0]["message"])
    assert "Action: Buy" in str(sent[0]["message"])
    assert "Profit now:" in str(sent[0]["message"])
    assert "LINKS" in str(sent[0]["message"])
    assert "AutoSniper page: https://autosniper.example/AI_ANALYSIS?listing_url=https%3A%2F%2Fexample.com%2Flot%2Fdecision-1" in str(sent[0]["message"])
    assert "Auction page: https://example.com/lot/decision-1" in str(sent[0]["message"])


def test_autosniper_listing_url_defaults_to_local_ai_analysis(monkeypatch) -> None:
    monkeypatch.delenv("AUTOSNIPER_AI_ANALYSIS_URL", raising=False)
    monkeypatch.delenv("AUTOSNIPER_APP_URL", raising=False)

    url = ai_listing_valuation._autosniper_listing_url("https://example.com/lot/1?a=b")

    assert url == "http://localhost:8501/AI_ANALYSIS?listing_url=https%3A%2F%2Fexample.com%2Flot%2F1%3Fa%3Db"


def test_listing_alert_does_not_send_for_watch_only(monkeypatch, tmp_path: Path) -> None:
    _set_alert_dataset_paths(monkeypatch, tmp_path)
    sent: list[object] = []
    monkeypatch.setattr(
        ai_listing_valuation,
        "send_on_state_change",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    ai_listing_valuation._maybe_send_listing_alerts(
        _base_saved_row(
            computed_verdict="Marginal (repairs)",
            verdict="Marginal (repairs)",
            action_label="Watch",
            bid_status="Below expected",
        ),
        None,
    )

    assert sent == []


def test_listing_alert_warns_when_potential_buy_has_unresolved_repairs(monkeypatch, tmp_path: Path) -> None:
    _set_alert_dataset_paths(monkeypatch, tmp_path)
    sent: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        ai_listing_valuation,
        "send_on_state_change",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    ai_listing_valuation._maybe_send_listing_alerts(
        _base_saved_row(
            action_label="Review",
            computed_verdict="Review (unresolved repairs)",
            potential_buy_unresolved_repairs=True,
            unresolved_repair_count=1,
            unresolved_repairs="rough idle",
        ),
        None,
    )

    assert len(sent) == 1
    args, _kwargs = sent[0]
    assert args[2] == "ai_analysis_buy_unresolved_repairs"
    assert "POTENTIAL BUY - UNRESOLVED REPAIRS" in str(args[3])
    assert "Unresolved repairs: rough idle" in str(args[3])
    assert "do not bid until these repairs are classified and repriced" in str(args[3])


def test_listing_alert_keeps_at_ceiling_buy_actionable(monkeypatch, tmp_path: Path) -> None:
    _set_alert_dataset_paths(monkeypatch, tmp_path)
    sent: list[object] = []
    monkeypatch.setattr(
        ai_listing_valuation,
        "send_on_state_change",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    ai_listing_valuation._maybe_send_listing_alerts(
        _base_saved_row(
            action_label="Buy",
            computed_verdict="Conditional Flip",
            verdict="Conditional Flip",
            bid_status="At ceiling",
            hard_max_safety="Conditional",
            expected_auction_worst_profit_value=2500.0,
            profit_at_current_bid_worst_value=2500.0,
        ),
        None,
    )

    assert len(sent) == 1
    assert sent[0][0][0] == "listing_bid_ready"
    assert sent[0][0][2] == "ai_analysis_buy"


def test_listing_alert_sends_when_buy_becomes_not_bid_ready(monkeypatch, tmp_path: Path) -> None:
    _set_alert_dataset_paths(monkeypatch, tmp_path)
    sent: list[dict[str, object]] = []

    def fake_send_on_state_change(alert_scope, url, state_value, message, verdict=None):
        sent.append(
            {
                "alert_scope": alert_scope,
                "url": url,
                "state_value": state_value,
                "message": message,
                "verdict": verdict,
            }
        )
        return True

    monkeypatch.setattr(ai_listing_valuation, "send_on_state_change", fake_send_on_state_change)

    ai_listing_valuation._maybe_send_listing_alerts(
        _base_saved_row(
            action_label="Avoid",
            bid_status="Over max",
            hard_max_safety="No edge",
            profit_at_current_bid_worst_value=500.0,
        ),
        _base_saved_row(action_label="Buy", bid_status="Cheap"),
    )

    assert len(sent) == 1
    assert sent[0]["alert_scope"] == "listing_bid_ready"
    assert sent[0]["state_value"] == "ai_analysis_not_buy"
    assert "BUY ALERT UPDATE - NO LONGER A BUY" in str(sent[0]["message"])
    assert "Alert type: Buy status changed" in str(sent[0]["message"])
    assert "Why sent: this listing was previously alerted as Buy, but AI Analysis changed." in str(sent[0]["message"])
    assert "STATUS" in str(sent[0]["message"])
    assert "Previous action: Buy" in str(sent[0]["message"])
    assert "Current action: Avoid" in str(sent[0]["message"])
    assert "LINKS" in str(sent[0]["message"])


def test_listing_alert_sends_not_buy_update_from_alert_state(monkeypatch, tmp_path: Path) -> None:
    _set_alert_dataset_paths(monkeypatch, tmp_path)
    sent: list[dict[str, object]] = []

    monkeypatch.setattr(
        ai_listing_valuation,
        "get_alert_state",
        lambda alert_scope, url: "ai_analysis_buy",
    )

    def fake_send_on_state_change(alert_scope, url, state_value, message, verdict=None):
        sent.append(
            {
                "alert_scope": alert_scope,
                "url": url,
                "state_value": state_value,
                "message": message,
                "verdict": verdict,
            }
        )
        return True

    monkeypatch.setattr(ai_listing_valuation, "send_on_state_change", fake_send_on_state_change)

    ai_listing_valuation._maybe_send_listing_alerts(
        _base_saved_row(action_label="Avoid", bid_status="Over max", computed_verdict="Avoid"),
        _base_saved_row(action_label="Avoid", bid_status="Over max", computed_verdict="Avoid"),
    )

    assert len(sent) == 1
    assert sent[0]["state_value"] == "ai_analysis_not_buy"
    assert "BUY ALERT UPDATE - NO LONGER A BUY" in str(sent[0]["message"])
    assert "Current action: Avoid" in str(sent[0]["message"])


def test_listing_alert_suppresses_stale_non_active_buy(monkeypatch, tmp_path: Path) -> None:
    _set_alert_dataset_paths(monkeypatch, tmp_path, active=False, referred=True)
    sent: list[object] = []
    monkeypatch.setattr(
        ai_listing_valuation,
        "send_on_state_change",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    ai_listing_valuation._maybe_send_listing_alerts(
        _base_saved_row(action_label="Buy", bid_status="Cheap"),
        None,
    )

    assert sent == []


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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

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


def test_curve_analysis_warns_when_autotrader_median_misses_curve_threshold(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=[],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=0,
        severity_level="none",
        severity_multiplier=1.0,
        total_cost=0,
        reasons=[],
    )
    listing = pd.Series(
        {
            "url": "test://autotrader-mismatch",
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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        autotrader_median=23_000,
        carsales_estimate=20_000,
        listings_cluster_ok=True,
        force_refresh=True,
    )

    assert ai_listing_valuation.AUTOTRADER_CURVE_WARNING_FLAG in result["risk_flags"]
    assert "Autotrader confirmation warning" in str(result["confidence_notes"])


def test_curve_analysis_keeps_autotrader_alignment_warning_quiet_within_threshold(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=[],
        cosmetic_panels=0,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=0,
        severity_level="none",
        severity_multiplier=1.0,
        total_cost=0,
        reasons=[],
    )
    listing = pd.Series(
        {
            "url": "test://autotrader-aligned",
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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        autotrader_median=21_500,
        carsales_estimate=20_000,
        listings_cluster_ok=True,
        force_refresh=True,
    )

    assert ai_listing_valuation.AUTOTRADER_CURVE_WARNING_FLAG not in result["risk_flags"]


def test_market_lifecycle_fast_clear_boosts_confidence() -> None:
    confidence, risk_flags, notes = ai_listing_valuation._apply_market_lifecycle_confidence(
        0.70,
        [],
        [],
        {"fast_clear_count": 2, "stale_active_count": 0},
    )

    assert round(confidence, 2) == 0.78
    assert risk_flags == []
    assert "disappeared within 5 days" in notes[0]


def test_market_lifecycle_stale_active_warns_and_reduces_confidence() -> None:
    confidence, risk_flags, notes = ai_listing_valuation._apply_market_lifecycle_confidence(
        0.70,
        [],
        [],
        {"fast_clear_count": 0, "stale_active_count": 3},
    )

    assert round(confidence, 2) == 0.62
    assert ai_listing_valuation.STALE_MARKET_FLAG in risk_flags
    assert "30+ days" in notes[0]


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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    assert result["computed_verdict"] == "Marginal (repairs)"
    assert result["action_label"] == "Buy"
    assert result["repair_estimate"] == "$2,250"


def test_curve_analysis_forces_review_when_repairs_are_unresolved(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=["COSMETIC_PANEL"],
        cosmetic_panels=1,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=300,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=300,
        reasons=["priced cosmetic repair"],
        fragments=[
            RepairFragment(
                original_text="rough idle.",
                normalized_text="rough idle",
                status="unclassified",
                category="unclassified",
            )
        ],
    )
    listing = pd.Series(
        {
            "url": "test://unresolved-repair",
            "price": "$1,000",
            "make": "Ford",
            "model": "Focus",
            "variant": "Trend",
            "body_type": "Hatch",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "Cosmetic damage, rough idle.",
        }
    )
    monkeypatch.setattr(
        ai_listing_valuation,
        "load_cached_results",
        lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS),
    )
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    assert result["computed_verdict"] == "Review (unresolved repairs)"
    assert result["action_label"] == "Review"
    assert result["potential_buy_unresolved_repairs"] is True
    assert result["unresolved_repair_count"] == 1
    assert result["unresolved_repairs"] == "rough idle"
    assert "UNRESOLVED_REPAIRS" in result["risk_flags"]
    assert "repair_certainty=0.50" in result["confidence_notes"]


def test_curve_analysis_forces_review_when_repair_quote_class_is_incompatible(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=["COSMETIC_PANEL"],
        cosmetic_panels=1,
        glass_cost=0,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=300,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=300,
        reasons=["fallback repair price"],
        pricing_vehicle_class="medium_suv",
        pricing_class_uncertain=True,
        pricing_incompatible_canonicals=["cosmetic_surface_damage"],
    )
    listing = pd.Series(
        {
            "url": "test://repair-pricing-class-gap",
            "price": "$1,000",
            "make": "Ford",
            "model": "Territory",
            "variant": "Trend",
            "body_type": "SUV",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "Front guard scratched.",
        }
    )
    monkeypatch.setattr(
        ai_listing_valuation,
        "load_cached_results",
        lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS),
    )
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    assert result["computed_verdict"] == "Review (repair pricing evidence)"
    assert result["action_label"] == "Review"
    assert result["potential_buy_repair_pricing_uncertain"] is True
    assert result["repair_pricing_vehicle_class"] == "medium_suv"
    assert result["repair_pricing_incompatible_canonicals"] == "cosmetic_surface_damage"
    assert "REPAIR_PRICING_CLASS_UNCERTAIN" in result["risk_flags"]


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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)
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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)
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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    economic_max_bid = ai_listing_valuation._parse_currency(result["economic_max_bid"])
    economic_current_profit = ai_listing_valuation._parse_currency(result["economic_profit_at_current_bid"])

    assert result["recommended_max_bid"] == "$0"
    assert result["bid_policy_gate"] == "INTERSTATE"
    assert economic_max_bid is not None and economic_max_bid > 0
    assert economic_current_profit is not None and economic_current_profit > 0
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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

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
    assert ai_listing_valuation._parse_currency(result["recommended_max_bid"]) == 13_714
    assert ai_listing_valuation._parse_currency(result["recommended_max_bid"]) > 6_200
    assert result["current_profit_label"] == "Strong"
    assert result["expected_auction_profit_label"] in {"Good", "Strong"}
    assert result["hard_max_safety"] in {"Conditional", "Strong"}
    assert result["bid_status"] == "Cheap"
    assert result["action_label"] == "Buy"


def test_curve_analysis_caps_expected_auction_for_reauction_context(monkeypatch) -> None:
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
            "url": "test://reauction-active",
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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_median=6_200,
        comps_count=5,
        analysis_context="active",
        reauction_context={
            "reauction_event_count": 1,
            "reauction_last_price": 5_500,
            "reauction_price_delta": -700,
        },
        force_refresh=True,
    )

    expected_profit = ai_listing_valuation._net_profit_value(20_000, 5_500, listing.to_dict())

    assert result["expected_auction_price"] == "$5,500"
    assert result["expected_auction_source"] == "historical_sold_median+reauction_latest_sale_cap"
    assert result["expected_auction_reauction_adjustment"] == "$-700"
    assert result["expected_auction_reauction_reason"] == "reauction_latest_sale_cap"
    assert result["reauction_event_count"] == 1
    assert result["reauction_last_price"] == "$5,500"
    assert ai_listing_valuation._parse_currency(result["expected_auction_profit"]) == round(expected_profit)


def test_curve_analysis_keeps_pajero_like_historical_comps_informational(monkeypatch) -> None:
    repair_assessment = RepairAssessment(
        hard_avoid=False,
        pills=["GLASS"],
        cosmetic_panels=0,
        glass_cost=350,
        replacement_cost=0,
        risk_buffer=0,
        base_cost=350,
        severity_level="minor",
        severity_multiplier=1.0,
        total_cost=350,
        reasons=["windscreen chip"],
    )
    listing = pd.Series(
        {
            "url": "test://pajero-regression",
            "price": "$4,900",
            "year": 2012,
            "make": "MITSUBISHI",
            "model": "Pajero",
            "variant": "glx",
            "body_type": "suv",
            "transmission": "Automatic",
            "fuel_type": "Diesel",
            "location": "melbourne",
            "rego_expiry": "Unregistered",
            "odometer_reading": 238_943,
            "general_condition": "windscreen chip",
        }
    )

    monkeypatch.setattr(ai_listing_valuation, "load_cached_results", lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS))
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=19_500,
        comps_median=6_200,
        comps_count=3,
        analysis_context="active",
        force_refresh=True,
    )

    assert result["expected_auction_price"] == "$6,200"
    assert result["expected_auction_source"] == "historical_sold_median"
    assert ai_listing_valuation._parse_currency(result["recommended_max_bid"]) == 10_716
    assert ai_listing_valuation._parse_currency(result["recommended_max_bid"]) > 6_200
    assert result["bid_status"] == "Cheap"
    assert result["action_label"] == "Buy"
    assert result["computed_verdict"] == "Conditional Flip"


def test_curve_analysis_refreshes_cached_rows_missing_display_fields(monkeypatch) -> None:
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
            "url": "test://stale-display-fields",
            "price": "$2,000",
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
    cached_row = {
        column: None
        for column in ai_listing_valuation.REQUIRED_COLUMNS
    }
    cached_row.update(
        {
            "url": "test://stale-display-fields",
            "analysis_timestamp": "2026-01-14T00:00:00+00:00",
            "analysis_context": "active",
            "expected_auction_price": "$6,200",
            "expected_auction_bid_basis": float("nan"),
            "expected_auction_source": "historical_sold_median",
            "expected_auction_profit": "$9,000",
            "action_label": "Watch",
            "current_profit_label": "Good",
            "discount_used": 0.75,
            "economic_max_bid": float("nan"),
            "economic_profit_at_current_bid": float("nan"),
            "economic_profit_at_current_bid_worst": float("nan"),
            "bid_status": float("nan"),
        }
    )

    monkeypatch.setattr(ai_listing_valuation, "load_cached_results", lambda: pd.DataFrame([cached_row]))
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_median=6_200,
        comps_count=5,
        analysis_context="active",
    )

    assert result["cached"] is False
    assert result["analysis_timestamp"] != "2026-01-14T00:00:00+00:00"
    assert result["expected_auction_bid_basis"] == "$6,200"
    assert result["economic_max_bid"]
    assert result["economic_profit_at_current_bid"]
    assert result["bid_status"] == "Cheap"


def test_curve_analysis_reuses_cached_row_when_input_hash_matches(monkeypatch) -> None:
    listing = pd.Series(
        {
            "url": "test://hash-cache-hit",
            "price": "$2,000",
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
    input_hash = ai_listing_valuation._valuation_input_hash(
        listing,
        resale_mid=20_000,
        comps_median=6_200,
        comps_count=5,
        analysis_context="active",
        km_percentile=None,
        autotrader_median=None,
        carsales_estimate=None,
        listings_cluster_ok=None,
    )
    cached_row = {column: "ok" for column in ai_listing_valuation.REQUIRED_COLUMNS}
    cached_row.update(
        {
            "url": "test://hash-cache-hit",
            "analysis_timestamp": "2026-01-14T00:00:00+00:00",
            "analysis_context": "active",
            "expected_auction_price": "$6,200",
            "expected_auction_bid_basis": "$6,200",
            "expected_auction_source": "historical_sold_median",
            "expected_auction_profit": "$9,000",
            "action_label": "Watch",
            "current_profit_label": "Good",
            "discount_used": 0.75,
            "economic_max_bid": "$3,700",
            "economic_profit_at_current_bid": "$8,000",
            "economic_profit_at_current_bid_worst": "$4,000",
            "bid_status": "Cheap",
            "valuation_input_hash": input_hash,
        }
    )

    monkeypatch.setattr(ai_listing_valuation, "load_cached_results", lambda: pd.DataFrame([cached_row]))

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_median=6_200,
        comps_count=5,
        analysis_context="active",
    )

    assert result["cached"] is True
    assert result["analysis_timestamp"] == "2026-01-14T00:00:00+00:00"


def test_curve_analysis_refreshes_cached_row_when_input_hash_changes(monkeypatch) -> None:
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
    cached_listing = pd.Series(
        {
            "url": "test://hash-cache-miss",
            "price": "$2,000",
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
    changed_listing = cached_listing.copy()
    changed_listing["price"] = "$2,500"
    old_hash = ai_listing_valuation._valuation_input_hash(
        cached_listing,
        resale_mid=20_000,
        comps_median=6_200,
        comps_count=5,
        analysis_context="active",
        km_percentile=None,
        autotrader_median=None,
        carsales_estimate=None,
        listings_cluster_ok=None,
    )
    cached_row = {column: "ok" for column in ai_listing_valuation.REQUIRED_COLUMNS}
    cached_row.update(
        {
            "url": "test://hash-cache-miss",
            "analysis_timestamp": "2026-01-14T00:00:00+00:00",
            "analysis_context": "active",
            "expected_auction_price": "$6,200",
            "expected_auction_bid_basis": "$6,200",
            "expected_auction_source": "historical_sold_median",
            "expected_auction_profit": "$9,000",
            "action_label": "Watch",
            "current_profit_label": "Good",
            "discount_used": 0.75,
            "economic_max_bid": "$3,700",
            "economic_profit_at_current_bid": "$8,000",
            "economic_profit_at_current_bid_worst": "$4,000",
            "bid_status": "Cheap",
            "valuation_input_hash": old_hash,
        }
    )

    monkeypatch.setattr(ai_listing_valuation, "load_cached_results", lambda: pd.DataFrame([cached_row]))
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        changed_listing,
        resale_mid=20_000,
        comps_median=6_200,
        comps_count=5,
        analysis_context="active",
    )

    assert result["cached"] is False
    assert result["analysis_timestamp"] != "2026-01-14T00:00:00+00:00"
    assert result["valuation_input_hash"] != old_hash


def test_curve_analysis_refreshes_cached_row_when_repair_rules_change(monkeypatch) -> None:
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
            "url": "test://repair-rules-cache-miss",
            "price": "$2,000",
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
    monkeypatch.setattr(ai_listing_valuation, "_repair_rules_signature", lambda: "old-repair-rules")
    old_hash = ai_listing_valuation._valuation_input_hash(
        listing,
        resale_mid=20_000,
        comps_median=6_200,
        comps_count=5,
        analysis_context="active",
        km_percentile=None,
        autotrader_median=None,
        carsales_estimate=None,
        listings_cluster_ok=None,
    )
    cached_row = {column: "ok" for column in ai_listing_valuation.REQUIRED_COLUMNS}
    cached_row.update(
        {
            "url": "test://repair-rules-cache-miss",
            "analysis_timestamp": "2026-01-14T00:00:00+00:00",
            "analysis_context": "active",
            "expected_auction_price": "$6,200",
            "expected_auction_bid_basis": "$6,200",
            "expected_auction_source": "historical_sold_median",
            "expected_auction_profit": "$9,000",
            "action_label": "Watch",
            "current_profit_label": "Good",
            "discount_used": 0.75,
            "economic_max_bid": "$3,700",
            "economic_profit_at_current_bid": "$8,000",
            "economic_profit_at_current_bid_worst": "$4,000",
            "bid_status": "Cheap",
            "valuation_input_hash": old_hash,
        }
    )

    monkeypatch.setattr(ai_listing_valuation, "_repair_rules_signature", lambda: "new-repair-rules")
    monkeypatch.setattr(ai_listing_valuation, "load_cached_results", lambda: pd.DataFrame([cached_row]))
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_median=6_200,
        comps_count=5,
        analysis_context="active",
    )

    assert result["cached"] is False
    assert result["analysis_timestamp"] != "2026-01-14T00:00:00+00:00"
    assert result["valuation_input_hash"] != old_hash


def test_curve_analysis_marks_low_expected_finish_profit_as_marginal(monkeypatch) -> None:
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
            "url": "test://expected-finish-marginal",
            "price": "$2,000",
            "make": "Hyundai",
            "model": "i30",
            "variant": "Active",
            "body_type": "Hatch",
            "transmission": "Auto",
            "fuel_type": "Petrol",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "",
            "service_history": "Yes",
            "owners_manual": "Yes",
            "key": "Yes",
            "spare_key": "Yes",
            "engine_turns_over": "Yes",
        }
    )

    monkeypatch.setattr(ai_listing_valuation, "load_cached_results", lambda: pd.DataFrame(columns=ai_listing_valuation.REQUIRED_COLUMNS))
    monkeypatch.setattr(ai_listing_valuation, "_save_result_row", lambda row: None)
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

    result = ai_listing_valuation.run_curve_listing_analysis(
        listing,
        resale_mid=20_000,
        comps_median=16_000,
        comps_count=5,
        analysis_context="active",
        force_refresh=True,
    )

    assert result["computed_verdict"] == "Marginal (expected finish)"
    assert result["action_label"] == "Buy"
    assert result["expected_auction_worst_profit_value"] < ai_listing_valuation.MIN_NET_PROFIT_ABSOLUTE
    assert result["net_profit_worst_value"] > 0


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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)
    monkeypatch.setattr(
        ai_listing_valuation,
        "_expected_auction_estimate",
        lambda resale_mid_val, comps_median=None, comps_count=None, model_prediction=None: (
            6_200,
            "historical_sold_median",
            5,
        ),
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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)
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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

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
    assert result["repair_estimate_low"] == "$10,000"
    assert result["repair_estimate_high"] == "$10,000"
    assert result["repair_estimate_low_value"] == 10_000
    assert result["repair_estimate_high_value"] == 10_000


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
    monkeypatch.setattr(ai_listing_valuation, "assess_repairs", lambda condition, **_kwargs: repair_assessment)

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
    assert result["repair_estimate_low"] == "$8,000"
    assert result["repair_estimate_high"] == "$8,000"
    assert "STRUCTURAL" in result["risk_flags"]


def test_transport_default_matches_local_operating_cost() -> None:
    assert ai_listing_valuation.DEFAULT_TRANSPORT == 200.0
    assert ai_listing_valuation.OPERATING_STATE == "VIC"
    assert ai_listing_valuation._estimate_transport_cost("Melbourne VIC") == 200.0
