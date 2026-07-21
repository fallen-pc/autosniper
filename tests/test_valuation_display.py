from __future__ import annotations

import pandas as pd

from shared.valuation_display import (
    active_profit_value,
    bid_display_parts,
    build_ai_analysis_summary_rows,
    conservative_margin_percent,
    expected_finish_profit_value,
    first_currency_value,
    is_safe_opportunity_row,
    recommended_max_bid_value,
    rank_live_opportunities,
)


def test_build_ai_analysis_summary_rows_matches_default_visible_ai_scope() -> None:
    active_df = pd.DataFrame(
        [
            {"url": "buy", "price": "$2,000", "year": 2018, "make": "Toyota", "location": "VIC"},
            {"url": "watch", "price": "$4,000", "year": 2017, "make": "Mazda", "location": "VIC"},
            {"url": "avoid", "price": "$5,000", "year": 2016, "make": "Ford", "location": "VIC"},
        ]
    )
    valuations_df = pd.DataFrame(
        [
            {
                "url": "buy", "analysis_timestamp": "2026-07-19T00:00:00Z",
                "action_label": "Buy", "computed_verdict": "Strong Flip", "bid_status": "Cheap",
                "hard_max_safety": "Strong", "expected_auction_comps_count": 4,
                "expected_auction_worst_profit": "$2,000", "profit_at_current_bid_worst": "$3,000",
                "recommended_max_bid": "$6,000", "net_profit_worst": "$2,500", "resale_mid": "$12,500",
                "confidence": 0.9,
            },
            {
                "url": "watch", "analysis_timestamp": "2026-07-19T00:00:00Z",
                "action_label": "Watch", "computed_verdict": "Conditional Flip", "bid_status": "Near ceiling",
                "hard_max_safety": "Conditional", "expected_auction_comps_count": 4,
                "expected_auction_worst_profit": "$500", "profit_at_current_bid_worst": "$1,500",
                "recommended_max_bid": "$4,500", "net_profit_worst": "$1,500", "resale_mid": "$10,000",
                "confidence": 0.8,
            },
            {
                "url": "avoid", "analysis_timestamp": "2026-07-19T00:00:00Z",
                "action_label": "Avoid", "computed_verdict": "Avoid", "bid_status": "Over max",
                "hard_max_safety": "Blocked", "recommended_max_bid": "$0", "net_profit_worst": "$500",
                "resale_mid": "$8,000", "confidence": 0.7,
            },
        ]
    )

    summary = build_ai_analysis_summary_rows(active_df, valuations_df, min_profit=1000)

    assert summary["url"].tolist() == ["buy", "watch"]
    assert summary["action_label"].tolist() == ["Buy", "Buy"]
    assert summary.loc[summary["url"] == "buy", "current_price_value"].item() == 2000
    assert summary.loc[summary["url"] == "buy", "max_bid_value"].item() == 6000


def test_first_currency_value_preserves_zero_before_fallback() -> None:
    assert first_currency_value("$0", "$12,000") == 0.0


def test_rank_live_opportunities_filters_unsafe_rows_and_uses_worst_profit() -> None:
    active_df = pd.DataFrame(
        [
            {"url": "safe", "price": "$10,000", "make": "Toyota", "model": "Corolla"},
            {"url": "trap", "price": "$10,000", "make": "Toyota", "model": "Corolla"},
            {"url": "zero", "price": "$100", "make": "Toyota", "model": "Corolla"},
            {"url": "no-edge", "price": "$10,000", "make": "Toyota", "model": "Corolla"},
        ]
    )
    valuations_df = pd.DataFrame(
        [
            {
                "url": "safe",
                "recommended_max_bid": "$13,000",
                "resale_mid": "$20,000",
                "net_profit_mid": "$5,000",
                "net_profit_worst": "$2,500",
                "profit_margin_percent": "12.5%",
                "confidence": 0.7,
                "computed_verdict": "Conditional Flip",
                "no_edge": False,
                "edge_buffer": 50,
            },
            {
                "url": "trap",
                "recommended_max_bid": "$18,000",
                "resale_mid": "$22,000",
                "net_profit_mid": "$8,000",
                "net_profit_worst": "$5,000",
                "profit_margin_percent": "20.0%",
                "confidence": 0.8,
                "computed_verdict": "Trap",
                "no_edge": False,
                "edge_buffer": 50,
            },
            {
                "url": "zero",
                "recommended_max_bid": "$0",
                "resale_mid": "$18,000",
                "net_profit_mid": "$3,000",
                "net_profit_worst": "$1,000",
                "profit_margin_percent": "5.5%",
                "confidence": 0.6,
                "computed_verdict": "Avoid",
                "no_edge": False,
                "edge_buffer": 50,
            },
            {
                "url": "no-edge",
                "recommended_max_bid": "$10,030",
                "resale_mid": "$18,000",
                "net_profit_mid": "$3,000",
                "net_profit_worst": "$1,000",
                "profit_margin_percent": "5.5%",
                "confidence": 0.6,
                "computed_verdict": "Conditional Flip",
                "no_edge": True,
                "edge_buffer": 50,
            },
        ]
    )

    ranked = rank_live_opportunities(active_df, valuations_df)

    assert ranked["url"].tolist() == ["safe"]
    assert ranked.iloc[0]["profit_value"] == 2500.0
    assert ranked.iloc[0]["max_bid_value"] == 13000.0


def test_rank_live_opportunities_prefers_typed_numeric_fields_over_display_text() -> None:
    active_df = pd.DataFrame(
        [
            {"url": "typed", "price": "$10,000", "make": "Toyota", "model": "Corolla"},
        ]
    )
    valuations_df = pd.DataFrame(
        [
            {
                "url": "typed",
                "recommended_max_bid": "$9,000",
                "recommended_max_bid_value": 13_000,
                "resale_mid": "$1",
                "resale_mid_value": 20_000,
                "net_profit_worst": "-$5",
                "net_profit_worst_value": 2_500,
                "profit_margin_percent": "-1.0%",
                "profit_margin_value": 12.5,
                "confidence": 0.7,
                "computed_verdict": "Conditional Flip",
                "no_edge": False,
                "edge_buffer": 50,
            },
        ]
    )

    ranked = rank_live_opportunities(active_df, valuations_df)

    assert ranked["url"].tolist() == ["typed"]
    assert ranked.iloc[0]["max_bid_value"] == 13_000
    assert ranked.iloc[0]["resale_mid_value"] == 20_000
    assert ranked.iloc[0]["profit_value"] == 2_500
    assert ranked.iloc[0]["margin_value"] == 12.5


def test_is_safe_opportunity_row_accepts_radar_profit_value() -> None:
    row = pd.Series(
        {
            "price": "$10,000",
            "recommended_max_bid": "$13,000",
            "profit_value": 2500.0,
            "computed_verdict": "Conditional Flip",
            "no_edge": False,
            "edge_buffer": 50,
        }
    )

    assert is_safe_opportunity_row(row) is True


def test_conservative_margin_percent_prefers_worst_profit_over_stored_margin() -> None:
    row = pd.Series(
        {
            "resale_mid": "$20,000",
            "net_profit_mid": "$6,000",
            "net_profit_worst": "$1,000",
            "profit_margin_percent": "30.0%",
        }
    )

    assert conservative_margin_percent(row) == 5.0


def test_active_profit_value_prefers_explicit_newer_fields() -> None:
    row = pd.Series(
        {
            "net_profit_worst": "$1,000",
            "expected_auction_profit": "$4,000",
            "expected_profit": "$9,000",
        }
    )

    assert active_profit_value(row) == 1000.0


def test_expected_finish_profit_value_prefers_expected_auction_profit() -> None:
    row = pd.Series(
        {
            "expected_auction_profit": "$2,500",
            "expected_profit": "$7,500",
        }
    )

    assert expected_finish_profit_value(row) == 2500.0


def test_recommended_max_bid_value_does_not_fallback_to_current_price() -> None:
    row = pd.Series(
        {
            "recommended_max_bid": None,
            "price": "$7,500",
        }
    )

    assert recommended_max_bid_value(row) is None


def test_bid_display_keeps_interstate_economics_visible_when_policy_blocks_bid() -> None:
    row = pd.Series(
        {
            "recommended_max_bid": "$0",
            "economic_max_bid": "$5,846",
            "current_bid_numeric": 4200,
            "bid_status": "Over max",
            "bid_policy_gate": "INTERSTATE",
        }
    )

    display = bid_display_parts(row)

    assert display["status"] == "Policy blocked"
    assert display["status_detail"] == "Interstate policy; economics cap $5,846"
    assert display["max_label"] == "No policy bid"
    assert display["max_detail"] == "Economics $5,846 before Interstate gate"


def test_bid_display_shows_room_for_live_economic_bid() -> None:
    row = pd.Series(
        {
            "recommended_max_bid": "$7,682",
            "economic_max_bid": "$7,682",
            "current_bid_numeric": 6400,
            "bid_status": "Above expected",
        }
    )

    display = bid_display_parts(row)

    assert display["status"] == "Above expected"
    assert display["status_detail"] == "Room $1,282 to proxy max $7,682"
    assert display["max_label"] == "$7,682"
    assert display["max_detail"] == "Enter as auction-site max; room $1,282"


def test_bid_display_treats_missing_policy_gate_as_empty() -> None:
    row = pd.Series(
        {
            "recommended_max_bid": "$7,121",
            "economic_max_bid": "$7,121",
            "current_bid_numeric": 4810,
            "bid_status": "Below expected",
            "bid_policy_gate": float("nan"),
        }
    )

    display = bid_display_parts(row)

    assert display["status"] == "Below expected"
    assert display["status_detail"] == "Room $2,311 to proxy max $7,121"
    assert display["max_label"] == "$7,121"
