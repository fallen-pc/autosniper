import pandas as pd

from scripts.generate_retail_median_outcomes import (
    MIN_RETAIL_MATCHES,
    _buy_price_basis,
    _retail_median_match,
)


def _retail_lane(prices: list[float], year: float = 2018, odometer: float = 100000) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "lane_key": "toyota|hilux|sr5|ute|diesel|auto",
                "retail_price": price,
                "year_numeric": year,
                "odometer_numeric": odometer,
            }
            for price in prices
        ]
    )


def test_retail_median_match_requires_minimum_sample_size() -> None:
    retail_by_lane = {"toyota|hilux|sr5|ute|diesel|auto": _retail_lane([30000, 31000, 32000])}
    row = pd.Series(
        {
            "lane_key": "toyota|hilux|sr5|ute|diesel|auto",
            "year_numeric": 2018,
            "odometer_numeric": 100000,
        }
    )
    median, count, status = _retail_median_match(row, retail_by_lane)
    assert median is None
    assert count == 3
    assert status == "thin_sample"


def test_retail_median_match_returns_median_with_enough_samples() -> None:
    prices = [30000, 31000, 32000, 33000, 34000]
    assert len(prices) >= MIN_RETAIL_MATCHES
    retail_by_lane = {"toyota|hilux|sr5|ute|diesel|auto": _retail_lane(prices)}
    row = pd.Series(
        {
            "lane_key": "toyota|hilux|sr5|ute|diesel|auto",
            "year_numeric": 2018,
            "odometer_numeric": 100000,
        }
    )
    median, count, status = _retail_median_match(row, retail_by_lane)
    assert median == 32000
    assert count == 5
    assert status == "ok"


def test_retail_median_match_excludes_year_outside_tolerance() -> None:
    retail_by_lane = {
        "toyota|hilux|sr5|ute|diesel|auto": _retail_lane([30000, 31000, 32000, 33000, 34000], year=2010)
    }
    row = pd.Series(
        {
            "lane_key": "toyota|hilux|sr5|ute|diesel|auto",
            "year_numeric": 2018,
            "odometer_numeric": 100000,
        }
    )
    median, count, status = _retail_median_match(row, retail_by_lane)
    assert median is None
    assert status == "no_year_match"


def test_retail_median_match_missing_lane() -> None:
    row = pd.Series({"lane_key": "missing|lane", "year_numeric": 2018, "odometer_numeric": 100000})
    median, count, status = _retail_median_match(row, {})
    assert median is None
    assert count == 0
    assert status == "no_lane_match"


def test_buy_price_basis_prefers_expected_auction_price() -> None:
    row = pd.Series(
        {
            "expected_auction_price_value": 15000.0,
            "recommended_max_bid_value": 12000.0,
            "current_bid_numeric": 9000.0,
        }
    )
    value, basis = _buy_price_basis(row)
    assert value == 15000.0
    assert basis == "expected_auction_price_value"


def test_buy_price_basis_falls_back_when_zero() -> None:
    row = pd.Series(
        {
            "expected_auction_price_value": 0.0,
            "recommended_max_bid_value": 12000.0,
            "current_bid_numeric": 9000.0,
        }
    )
    value, basis = _buy_price_basis(row)
    assert value == 12000.0
    assert basis == "recommended_max_bid_value"
