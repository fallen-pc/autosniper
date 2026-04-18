from __future__ import annotations

import pandas as pd

from shared.valuation_display import first_currency_value, is_safe_opportunity_row, rank_live_opportunities


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
