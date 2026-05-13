import pandas as pd

from scripts.generate_opportunity_lanes import _norm_text, _summarise_lane


def test_norm_text_treats_nan_as_blank() -> None:
    assert _norm_text(float("nan")) == ""


def test_summarise_lane_flags_year_mismatch() -> None:
    retail = pd.DataFrame(
        [
            {
                "lane_key": "toyota|example|base|wagon|petrol|auto",
                "make_key": "toyota",
                "model_key": "example",
                "variant_family": "base",
                "body_key": "wagon",
                "fuel_key": "petrol",
                "trans_key": "auto",
                "retail_price": 40000,
                "year_numeric": 2024,
                "odometer_numeric": 20000,
                "canonical_tag": "UNCLASSIFIED",
                "url": "https://retail.example/1",
            },
            {
                "lane_key": "toyota|example|base|wagon|petrol|auto",
                "make_key": "toyota",
                "model_key": "example",
                "variant_family": "base",
                "body_key": "wagon",
                "fuel_key": "petrol",
                "trans_key": "auto",
                "retail_price": 42000,
                "year_numeric": 2024,
                "odometer_numeric": 22000,
                "canonical_tag": "UNCLASSIFIED",
                "url": "https://retail.example/2",
            },
            {
                "lane_key": "toyota|example|base|wagon|petrol|auto",
                "make_key": "toyota",
                "model_key": "example",
                "variant_family": "base",
                "body_key": "wagon",
                "fuel_key": "petrol",
                "trans_key": "auto",
                "retail_price": 41000,
                "year_numeric": 2024,
                "odometer_numeric": 21000,
                "canonical_tag": "UNCLASSIFIED",
                "url": "https://retail.example/3",
            },
        ]
    )
    sold = pd.DataFrame(
        [
            {
                "lane_key": "toyota|example|base|wagon|petrol|auto",
                "sold_price": 10000,
                "year_numeric": 2016,
                "odometer_numeric": 160000,
                "canonical_tag": "UNCLASSIFIED",
                "url": "https://sold.example/1",
                "canonical_reason": "[OUT_OF_SCOPE]",
            },
            {
                "lane_key": "toyota|example|base|wagon|petrol|auto",
                "sold_price": 11000,
                "year_numeric": 2016,
                "odometer_numeric": 170000,
                "canonical_tag": "UNCLASSIFIED",
                "url": "https://sold.example/2",
                "canonical_reason": "[OUT_OF_SCOPE]",
            },
        ]
    )

    report = _summarise_lane(retail, sold, supported_curve_tags=set())

    assert report.loc[0, "recommendation"] == "year_mismatch"
    assert report.loc[0, "median_year_gap"] == 8
