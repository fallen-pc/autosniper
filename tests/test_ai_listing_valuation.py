from __future__ import annotations

from scripts import ai_listing_valuation


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
