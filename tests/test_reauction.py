import pandas as pd

from shared.reauction import (
    adjusted_expected_auction_price,
    collapse_reauction_lifecycles,
    reauction_context_for_listing,
)


def test_collapse_reauction_lifecycles_keeps_latest_sale_with_summary() -> None:
    df = pd.DataFrame(
        [
            {
                "url": "test://first",
                "vin": "MR0KA3CD201195598",
                "odometer_reading": "138,896",
                "price": "$20,200",
                "date_sold": "2025-08-17",
            },
            {
                "url": "test://latest",
                "vin": "MR0KA3CD201195598",
                "odometer_reading": "138896",
                "price": "$22,300",
                "date_sold": "2025-09-07",
            },
            {
                "url": "test://other",
                "vin": "",
                "odometer_reading": "10,000",
                "price": "$5,000",
                "date_sold": "2025-09-01",
            },
        ]
    )

    collapsed = collapse_reauction_lifecycles(df)

    assert set(collapsed["url"]) == {"test://latest", "test://other"}
    latest = collapsed[collapsed["url"] == "test://latest"].iloc[0]
    assert latest["reauction_event_count"] == 2
    assert latest["reauction_first_price"] == 20_200
    assert latest["reauction_last_price"] == 22_300
    assert latest["reauction_price_delta"] == 2_100
    assert latest["reauction_price_range"] == 2_100


def test_reauction_context_caps_expected_finish_at_latest_sale() -> None:
    sold_df = pd.DataFrame(
        [
            {
                "vin": "VIN12345678901234",
                "odometer_reading": "91,445",
                "price": "$28,250",
                "date_sold": "2026-04-06",
            }
        ]
    )
    listing = {"vin": "VIN12345678901234", "odometer_reading": "91445"}

    context = reauction_context_for_listing(listing, sold_df)
    adjusted, delta, reason = adjusted_expected_auction_price(32_000, context)

    assert context["reauction_last_price"] == 28_250
    assert adjusted == 28_250
    assert delta == -3_750
    assert reason == "reauction_latest_sale_cap"


def test_reauction_context_preserves_collapsed_lifecycle_summary() -> None:
    sold_df = collapse_reauction_lifecycles(
        pd.DataFrame(
            [
                {
                    "vin": "VIN12345678901234",
                    "odometer_reading": "91,445",
                    "price": "$27,000",
                    "date_sold": "2026-03-20",
                },
                {
                    "vin": "VIN12345678901234",
                    "odometer_reading": "91,445",
                    "price": "$25,500",
                    "date_sold": "2026-04-06",
                },
            ]
        )
    )
    listing = {"vin": "VIN12345678901234", "odometer_reading": "91445"}

    context = reauction_context_for_listing(listing, sold_df)

    assert len(sold_df) == 1
    assert context["reauction_event_count"] == 2
    assert context["reauction_first_price"] == 27_000
    assert context["reauction_last_price"] == 25_500
    assert context["reauction_price_delta"] == -1_500


def test_reauction_context_does_not_raise_expected_finish() -> None:
    context = {"reauction_event_count": 1, "reauction_last_price": 28_250}

    adjusted, delta, reason = adjusted_expected_auction_price(25_000, context)

    assert adjusted == 25_000
    assert delta == 0
    assert reason == "reauction_history_no_cap"
