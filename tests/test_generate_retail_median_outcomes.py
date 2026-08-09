import pandas as pd

from scripts.generate_retail_median_outcomes import (
    MIN_RETAIL_MATCHES,
    _buy_price_basis,
    generate_retail_median_outcomes,
    _merge_listing_details,
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


def test_buy_price_basis_uses_legacy_formatted_fields() -> None:
    row = pd.Series(
        {
            "expected_auction_price_value": pd.NA,
            "recommended_max_bid_value": pd.NA,
            "recommended_max_bid": "$12,000",
        }
    )

    value, basis = _buy_price_basis(row)

    assert value == 12000.0
    assert basis == "recommended_max_bid"


def test_merge_listing_details_backfills_missing_identity(tmp_path) -> None:
    valuations = pd.DataFrame(
        [
            {
                "url": "u1",
                "year": pd.NA,
                "make": pd.NA,
                "model": pd.NA,
                "variant": pd.NA,
                "body_type": pd.NA,
                "transmission": pd.NA,
                "fuel_type": pd.NA,
                "odometer_reading": pd.NA,
            }
        ]
    )
    details_path = tmp_path / "sold_cars.csv"
    pd.DataFrame(
        [
            {
                "url": "u1",
                "year": 2016,
                "make": "Holden",
                "model": "Cruze",
                "variant": "Equipe",
                "body_type": "Hatchback",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "odometer_reading": 99385,
            }
        ]
    ).to_csv(details_path, index=False)

    merged = _merge_listing_details(valuations, (details_path,))
    row = merged.iloc[0]

    assert row["year"] == 2016
    assert row["make"] == "Holden"
    assert row["model"] == "Cruze"
    assert row["body_type"] == "Hatchback"
    assert row["odometer_reading"] == 99385


def test_generate_profit_treats_blank_repair_high_as_zero(tmp_path) -> None:
    valuations_path = tmp_path / "valuations.csv"
    details_path = tmp_path / "details.csv"
    retail_path = tmp_path / "retail.csv"
    output_path = tmp_path / "outcomes.csv"

    pd.DataFrame(
        [
            {
                "url": "u1",
                "analysis_timestamp": "2026-01-01T00:00:00Z",
                "year": 2018,
                "make": "Toyota",
                "model": "Hilux",
                "variant": "SR5",
                "body_type": "Ute",
                "transmission": "Automatic",
                "fuel_type": "Diesel",
                "odometer_reading": 100000,
                "recommended_max_bid": "$20,000",
                "fees_estimate": "$500",
                "repair_estimate_high_value": pd.NA,
            }
        ]
    ).to_csv(valuations_path, index=False)
    pd.DataFrame([{"url": "u1"}]).to_csv(details_path, index=False)
    pd.DataFrame(
        [
            {
                "url": f"retail-{idx}",
                "year": 2018,
                "make": "Toyota",
                "model": "Hilux",
                "variant": "SR5",
                "body_type": "Ute",
                "transmission": "Automatic",
                "fuel_type": "Diesel",
                "odometer": 100000,
                "price": price,
            }
            for idx, price in enumerate([30000, 31000, 32000, 33000, 34000])
        ]
    ).to_csv(retail_path, index=False)

    output = generate_retail_median_outcomes(
        valuations_path=valuations_path,
        static_details_path=details_path,
        active_details_path=tmp_path / "missing_active.csv",
        sold_details_path=tmp_path / "missing_sold.csv",
        carsales_path=retail_path,
        autotrader_path=tmp_path / "missing_autotrader.csv",
        output_path=output_path,
    )

    row = output.iloc[0]
    assert row["simulated_retail_median"] == 32000.0
    assert row["simulated_profit"] == 11500.0
    assert "within +/-2yr" in row["outcome_note"]


def test_generate_profit_marks_missing_policy_inputs(tmp_path) -> None:
    valuations_path = tmp_path / "valuations.csv"
    details_path = tmp_path / "details.csv"
    retail_path = tmp_path / "retail.csv"
    output_path = tmp_path / "outcomes.csv"

    pd.DataFrame(
        [
            {
                "url": "u1",
                "analysis_timestamp": "2026-01-01T00:00:00Z",
                "year": 2018,
                "make": "Toyota",
                "model": "Hilux",
                "variant": "SR5",
                "body_type": "Ute",
                "transmission": "Automatic",
                "fuel_type": "Diesel",
                "odometer_reading": 100000,
                "computed_verdict": "Conditional Flip",
                "recommended_max_bid": "$20,000",
                "fees_estimate": "$500",
            }
        ]
    ).to_csv(valuations_path, index=False)
    pd.DataFrame([{"url": "u1"}]).to_csv(details_path, index=False)
    pd.DataFrame(
        [
            {
                "url": f"retail-{idx}",
                "year": 2018,
                "make": "Toyota",
                "model": "Hilux",
                "variant": "SR5",
                "body_type": "Ute",
                "transmission": "Automatic",
                "fuel_type": "Diesel",
                "odometer": 100000,
                "price": price,
            }
            for idx, price in enumerate([30000, 31000, 32000, 33000, 34000])
        ]
    ).to_csv(retail_path, index=False)

    output = generate_retail_median_outcomes(
        valuations_path=valuations_path,
        static_details_path=details_path,
        active_details_path=tmp_path / "missing_active.csv",
        sold_details_path=tmp_path / "missing_sold.csv",
        carsales_path=retail_path,
        autotrader_path=tmp_path / "missing_autotrader.csv",
        output_path=output_path,
    )

    row = output.iloc[0]
    assert row["policy_resolution_status"] == "missing_policy_inputs"
    assert row["missing_policy_inputs"] == "bid_status|hard_max_safety"
    assert row["action_label_display"] == "Missing policy inputs"
