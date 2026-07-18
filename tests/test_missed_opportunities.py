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
    monkeypatch.setattr(missed_opportunities, "assess_repairs", lambda condition, **_kwargs: _repair_assessment())

    result = missed_opportunities.compute_decision_metrics(
        row,
        20_000,
        include_repairs=True,
    )

    assert result["expected_auction_price"] == 15_000
    assert result["max_bid"] == 12_440
    assert result["repair_cost"] == 700
    assert result["risk_buffer"] == 300
    assert result["projected_profit_at_sold"] == 7351


def test_load_external_auction_sold_rows_keeps_only_settled_price_rows(tmp_path) -> None:
    path = tmp_path / "external_auction_curve_matches.csv"
    pd.DataFrame(
        [
            {
                "source": "pickles",
                "url": "https://www.pickles.com.au/used/details/cars/sold/1",
                "price": "$8,100",
                "status": "Sold",
                "date_sold": "11 July 2026",
                "canonical_tag": "toyota_corolla_zre182r_hatch_auto_petrol",
                "canonical_reason": "[OK]",
            },
            {
                "source": "manheim",
                "url": "https://www.manheim.com.au/passenger-vehicles/active/2",
                "price": "$7,500",
                "status": "Active",
                "date_sold": "",
                "canonical_tag": "toyota_corolla_zre182r_hatch_auto_petrol",
                "canonical_reason": "[OK]",
            },
            {
                "source": "slattery",
                "url": "https://slatteryauctions.com.au/assets/3",
                "price": "",
                "status": "Closed",
                "date_sold": "11/07/2026",
                "canonical_tag": "toyota_corolla_zre182r_hatch_auto_petrol",
                "canonical_reason": "[OK]",
            },
        ]
    ).to_csv(path, index=False)

    rows = missed_opportunities.load_external_auction_sold_rows(path)

    assert rows["url"].tolist() == ["https://www.pickles.com.au/used/details/cars/sold/1"]
    assert rows.iloc[0]["source"] == "pickles"
    assert rows.iloc[0]["price_numeric"] == 8100
    assert rows.iloc[0]["canonical_tag"] == "toyota_corolla_zre182r_hatch_auto_petrol"


def test_load_external_auction_sold_rows_accepts_closed_date_text(tmp_path) -> None:
    path = tmp_path / "external_auction_curve_matches.csv"
    pd.DataFrame(
        [
            {
                "source": "manheim",
                "url": "https://www.manheim.com.au/passenger-vehicles/sold/4",
                "price": "$9,200",
                "time_remaining_or_date_sold": "Closed 11/07/2026",
                "canonical_tag": "toyota_corolla_zre182r_hatch_auto_petrol",
                "canonical_reason": "[OK]",
            },
        ]
    ).to_csv(path, index=False)

    rows = missed_opportunities.load_external_auction_sold_rows(path)

    assert rows["url"].tolist() == ["https://www.manheim.com.au/passenger-vehicles/sold/4"]
    assert rows.iloc[0]["date_sold"] == "Closed 11/07/2026"


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
    monkeypatch.setattr(missed_opportunities, "assess_repairs", lambda condition, **_kwargs: _repair_assessment())

    result = missed_opportunities.compute_decision_metrics(
        row,
        20_000,
        include_repairs=False,
    )

    assert result["max_bid"] == 13_440
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
    monkeypatch.setattr(missed_opportunities, "assess_repairs", lambda condition, **_kwargs: _repair_assessment(total_cost=0, risk_buffer=0))

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
        lambda condition, **_kwargs: _repair_assessment(total_cost=0, risk_buffer=0),
    )

    result = missed_opportunities.compute_decision_metrics(
        row,
        20_000,
        include_repairs=True,
    )

    assert result["expected_auction_price"] == 12_300
    assert result["max_bid"] == 13_440


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
        lambda condition, **_kwargs: _repair_assessment(total_cost=0, risk_buffer=0),
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


def test_missed_decision_metrics_keeps_thin_comps_informational(monkeypatch) -> None:
    row = pd.Series(
        {
            "url": "test://missed-thin-comps",
            "price_numeric": 10_000,
            "price": "$10,000",
            "body_type": "Hatch",
            "location": "Melbourne VIC",
            "rego_state": "VIC",
            "general_condition": "",
            "historical_match_count": 2,
        }
    )

    monkeypatch.setattr(missed_opportunities, "_solve_max_bid", lambda resale_low, min_profit, listing: 20_000)
    monkeypatch.setattr(
        missed_opportunities,
        "assess_repairs",
        lambda condition, **_kwargs: _repair_assessment(total_cost=0, risk_buffer=0),
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
            "price_numeric": 14_000,
            "price": "$14,000",
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
        lambda condition, **_kwargs: _repair_assessment(total_cost=0, risk_buffer=0),
    )

    result = missed_opportunities.compute_decision_metrics(
        row,
        20_000,
        include_repairs=True,
    )

    assert result["max_bid"] == 13_440
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


def test_historical_comps_context_prefers_exact_year_then_group() -> None:
    sold_df = pd.DataFrame(
        [
            {"canonical_tag": "toyota_corolla_hatch", "year": 2018, "price": "$10,000"},
            {"canonical_tag": "toyota_corolla_hatch", "year": 2018, "price": "$12,000"},
            {"canonical_tag": "toyota_corolla_hatch", "year": 2019, "price": "$14,000"},
        ]
    )
    group_stats, year_stats = missed_opportunities.build_historical_comps_stats(sold_df)

    exact = missed_opportunities.historical_comps_for_row(
        {"year": 2018},
        curve_tag="toyota_corolla_hatch",
        year_stats=year_stats,
        group_stats=group_stats,
    )
    fallback = missed_opportunities.historical_comps_for_row(
        {"year": 2020},
        curve_tag="toyota_corolla_hatch",
        year_stats=year_stats,
        group_stats=group_stats,
    )

    assert exact["historical_match_count"] == 2
    assert exact["historical_price_median"] == 11_000
    assert fallback["historical_match_count"] == 3
    assert fallback["historical_price_median"] == 12_000


def test_historical_comps_context_excludes_current_sold_row_by_url() -> None:
    sold_df = pd.DataFrame(
        [
            {"url": "test://self", "canonical_tag": "toyota_corolla_hatch", "year": 2018, "price": "$10,000"},
            {"url": "test://peer-same-year", "canonical_tag": "toyota_corolla_hatch", "year": 2018, "price": "$12,000"},
            {"url": "test://peer-other-year", "canonical_tag": "toyota_corolla_hatch", "year": 2019, "price": "$14,000"},
        ]
    )
    group_stats, year_stats = missed_opportunities.build_historical_comps_stats(sold_df)

    exact = missed_opportunities.historical_comps_for_row(
        {"url": "test://self", "year": 2018},
        curve_tag="toyota_corolla_hatch",
        year_stats=year_stats,
        group_stats=group_stats,
    )
    fallback = missed_opportunities.historical_comps_for_row(
        {"url": "test://peer-other-year", "year": 2019},
        curve_tag="toyota_corolla_hatch",
        year_stats=year_stats,
        group_stats=group_stats,
    )

    assert exact["historical_match_count"] == 1
    assert exact["historical_price_median"] == 12_000
    assert fallback["historical_match_count"] == 2
    assert fallback["historical_price_median"] == 11_000
