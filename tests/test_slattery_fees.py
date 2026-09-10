from __future__ import annotations

import copy
import json

import pandas as pd
import pytest

from scripts import ai_listing_valuation as val
from shared import missed_opportunities as replay
from shared.auction_fees import (
    FeeEvidenceError, auction_operator, extract_slattery_fee_fields,
    fee_evidence_problem, slattery_buyer_charges, slattery_fee_breakpoints,
)
from shared.decision_economics import calculate_curve_decision_economics
from shared.repair_pricing import RepairAssessment


URL = "https://slatteryauctions.com.au/assets/137614?auctionId=10301"


def _asset() -> dict:
    # Public RAV4 asset 137614, observed 2026-09-09 and official calculator
    # arithmetic rechecked 2026-09-11. Two rows in the middle band are additive.
    return {"id": 137614, "sfid": "02iOa00000EHP8PIAX", "auctionId": 10301, "chargePrices": [
        {"id": i, "chargeType": "Buyer Charge", "assetType": "Motor Vehicle",
         "salesPriceLowerBound": lo, "salesPriceUpperBound": hi,
         "flatAmountInclGst": 0, "chargeRateInclGst": rate,
         "chargeRateMinimumInclGst": minimum}
        for i, lo, hi, rate, minimum in [
            (1, 65000.01, None, 2.75, 0), (70, 0, 5000, 0, 550),
            (71, 5000.01, 65000, 0, 715), (8709, 5000.01, 65000, 1.65, 0),
        ]
    ]}


def _listing() -> dict:
    return {
        "url": URL, "source": "slattery", "location": "Melbourne VIC",
        "rego_expiry": "2027-01-01", "rego_no": "ABC123",
        "make": "Toyota", "model": "Corolla", "body_type": "Hatch",
        "transmission": "Auto", "fuel_type": "Petrol", "year": 2018,
        "general_condition": "", "price": "$1,000", "price_numeric": 1000,
        "service_history": "Yes", "engine_turns_over": "Yes", "key": "Yes",
        "owners_manual": "Yes", "odometer_reading": 50000,
        **extract_slattery_fee_fields(_asset(), URL),
    }


def _repair(cost=0, high=0):
    return RepairAssessment(
        hard_avoid=False, pills=[], cosmetic_panels=0, glass_cost=0,
        replacement_cost=0, risk_buffer=0, base_cost=cost, severity_level="minor",
        severity_multiplier=1.0, total_cost=cost, total_cost_high=high,
        reasons=[],
    )


@pytest.mark.parametrize("url,source,expected", [
    (URL + "&utm_source=grays", "slattery", "slattery"),
    ("https://www.grays.com/lot/123", "grays", "grays"),
    ("https://grays.com.attacker.example/lot/123", "", "unknown"),
    ("https://grays.com@attacker.example/lot/123", "", "unknown"),
    ("https://example.com/grays/lot/123?platform=grays", "", "unknown"),
    (URL, "grays", "conflict"),
    ("https://slatteryauctions.com.au.attacker.example/assets/123", "slattery", "conflict"),
])
def test_verified_operator_ignores_tracking_and_rejects_conflicts(url, source, expected):
    listing = {"url": url, "source": source}
    assert auction_operator(listing) == expected
    assert val._is_grays_listing(listing) == (expected == "grays")


def test_slattery_referral_charges_never_use_grays_fee_or_admin():
    listing = _listing()
    listing["url"] += "&utm_source=grays"
    components = val._estimate_bid_cost_components(6000, listing)
    assert components["auction_fee"] == 814
    assert components["administration_fee"] == 0


@pytest.mark.parametrize("bid,expected", [
    (1000, 550 + 1550 * .0165), (4449.99, 550 + 4999.99 * .0165),
    (4450, 550), (5000, 550), (5000.01, 715 + 5000.01 * .0165),
    (65000, 1787.5), (65000.01, 65000.01 * .0275),
])
def test_observed_schedule_and_card_threshold_arithmetic(bid, expected):
    assert slattery_buyer_charges(bid, _listing()) == pytest.approx(expected)


@pytest.mark.parametrize("mutation", [
    lambda x: x.pop("auction_fee_schedule"),
    lambda x: x.update(source="grays"),
    lambda x: x.update(auction_fee_schedule="not-json"),
    lambda x: x.update(url=URL.replace("137614", "99999")),
    lambda x: x.update(auction_fee_status="unsupported"),
    lambda x: x.update(auction_fee_evidence_url="https://[broken"),
])
def test_unverified_fees_fail_closed_in_live_and_replay(monkeypatch, mutation):
    listing = _listing()
    mutation(listing)
    monkeypatch.setattr(val, "load_cached_results", lambda: pd.DataFrame(columns=val.REQUIRED_COLUMNS))
    monkeypatch.setattr(val, "_save_result_row", lambda row: None)
    assert fee_evidence_problem(listing)
    with pytest.raises(FeeEvidenceError):
        val._estimate_costs(5000, listing)
    assert val._solve_max_bid(20000, 1000, listing) == 0
    live = val.run_curve_listing_analysis(pd.Series(listing), 20000, force_refresh=True)
    historical = replay.compute_decision_metrics(pd.Series(listing), 20000, include_repairs=True)
    assert live["recommended_max_bid_value"] == historical["max_bid"] == 0
    assert live["computed_verdict"] == historical["computed_verdict"] == "Review (auction fee evidence)"
    assert live["action_label"] == historical["action_label"] == "Review"
    assert live["fees_estimate"] is None and historical["platform_fees"] is None
    assert live["profit_at_current_bid_worst_value"] is None
    assert historical["projected_profit_worst_at_sold"] is None


def test_invalid_partial_or_unsupported_charges_are_not_promoted():
    for change in ("partial", "nan", "category", "duplicate", "missing_gst"):
        asset = _asset()
        if change == "partial":
            asset["chargePrices"] = asset["chargePrices"][:1]
        elif change == "nan":
            asset["chargePrices"][0]["chargeRateInclGst"] = float("nan")
        elif change == "category":
            asset["chargePrices"][0]["assetType"] = "General Goods"
        elif change == "duplicate":
            asset["chargePrices"].append(copy.deepcopy(asset["chargePrices"][0]))
        else:
            asset["chargePrices"][0].pop("chargeRateInclGst")
        result = extract_slattery_fee_fields(asset, URL)
        assert result["auction_fee_schedule"] == ""
        assert result["auction_fee_status"] == "unsupported"


@pytest.mark.parametrize("url", [URL.replace("137614", "99999"), URL.replace("10301", "99999")])
def test_fee_extraction_refuses_a_different_asset_or_auction(url):
    assert extract_slattery_fee_fields(_asset(), url)["auction_fee_status"] == "unsupported"


def test_real_custom_schedule_starting_at_one_cent_is_supported():
    # Observed on assets 140397/140400 in auction 11023 on 2026-09-11.
    asset = _asset()
    asset["chargePrices"] = [{
        "id": 77269, "chargeType": "Buyer Charge", "assetType": "Motor Vehicle",
        "salesPriceLowerBound": 0.01, "salesPriceUpperBound": None,
        "flatAmountInclGst": 0, "chargeRateInclGst": 7.7, "chargeRateMinimumInclGst": 0,
        "isStandard": False,
    }]
    listing = {**_listing(), **extract_slattery_fee_fields(asset, URL)}
    assert not fee_evidence_problem(listing)
    assert slattery_buyer_charges(0, listing) == 0
    assert slattery_buyer_charges(0.01, listing) == pytest.approx(.00077 + .01077 * .0165)
    assert slattery_buyer_charges(6000, listing) == pytest.approx(462)
    cap = val._solve_max_bid(10000, 4000, listing)
    assert cap > 0
    prices = [cap] + [p for p in slattery_fee_breakpoints(listing) if p < cap]
    assert min(val._net_profit_value(10000, bid, listing) for bid in prices) >= 4000
    asset["chargePrices"][0]["salesPriceLowerBound"] = 0.02
    assert extract_slattery_fee_fields(asset, URL)["auction_fee_status"] == "unsupported"


def test_unsupported_fee_reason_is_specific_and_bounded():
    listing = _listing()
    listing.update(auction_fee_status="unsupported", auction_fee_schedule="",
                   auction_fee_evidence_text="Incomplete Slattery fee ranges")
    assert fee_evidence_problem(listing) == "Unsupported Slattery fee evidence: Incomplete Slattery fee ranges"
    listing["auction_fee_evidence_text"] = "untrusted arbitrary page contents"
    assert fee_evidence_problem(listing) == "Unsupported lot-specific Slattery fee evidence"


def test_proxy_cap_protects_all_lower_prices_at_card_fee_drop():
    listing = _listing()
    # At $4,450 the card surcharge disappears. A cap safe only at $4,450
    # would be unsafe if the proxy instead won at $4,449.99.
    net_at_drop = val._net_profit_value(10000, 4450, listing)
    cap = val._solve_max_bid(10000, net_at_drop, listing)
    assert cap < 4450
    assert 4449.99 in slattery_fee_breakpoints(listing)
    for bid in range(int(cap) + 1):
        assert val._net_profit_value(10000, bid, listing) >= net_at_drop


@pytest.mark.parametrize("repair_cost", [0, 100, 650])
def test_repair_inclusive_slattery_cap_keeps_minimum_profit(repair_cost):
    listing = _listing()
    result = calculate_curve_decision_economics(
        listing, resale_mid=12000, resale_low=10000, observed_price=1000,
        min_net_profit=3500, repair_assessment=_repair(repair_cost, repair_cost),
        solve_max_bid=val._solve_max_bid, estimate_costs=val._estimate_costs,
    )
    cap = result.proxy_max_bid
    assert cap > 0
    prices = [cap] + [p for p in slattery_fee_breakpoints(listing) if p < cap]
    assert min(val._net_profit_value(10000, bid, listing) - repair_cost for bid in prices) >= 3500


@pytest.mark.parametrize("resale", [8500, 10000, 20000, 100000])
def test_valid_schedule_live_replay_parity(monkeypatch, resale):
    listing = _listing()
    monkeypatch.setattr(val, "load_cached_results", lambda: pd.DataFrame(columns=val.REQUIRED_COLUMNS))
    monkeypatch.setattr(val, "_save_result_row", lambda row: None)
    monkeypatch.setattr(val, "assess_repairs", lambda *a, **k: _repair(100, 200))
    monkeypatch.setattr(replay, "assess_repairs", lambda *a, **k: _repair(100, 200))
    live = val.run_curve_listing_analysis(pd.Series(listing), resale, comps_count=5, force_refresh=True)
    historical = replay.compute_decision_metrics(pd.Series(listing), resale, include_repairs=True)
    assert live["recommended_max_bid_value"] == historical["max_bid"]
    assert live["profit_at_current_bid_worst_value"] == historical["projected_profit_worst_at_sold"]
    assert live["action_label"] == historical["action_label"]
    assert live["hard_max_safety"] == historical["hard_max_safety"]


def test_fee_evidence_is_in_valuation_cache_key():
    assert set(("source", "platform", "auction_operator", "auction_fee_schedule", "auction_fee_status")) <= set(val.VALUATION_INPUT_FIELDS)
    listing = _listing()
    changed = dict(listing)
    schedule = json.loads(changed["auction_fee_schedule"])
    schedule["charges"][1]["minimum"] += 100
    changed["auction_fee_schedule"] = json.dumps(schedule)
    kwargs = dict(resale_mid=20000, comps_median=None, comps_count=None, analysis_context=None,
                  km_percentile=None, autotrader_median=None, carsales_estimate=None, listings_cluster_ok=None)
    assert val._valuation_input_hash(listing, **kwargs) != val._valuation_input_hash(changed, **kwargs)
