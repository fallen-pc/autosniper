import pandas as pd

from shared.curve_builder_v2 import (
    prepare_active_market_for_proposal,
    propose_curve_from_evidence,
)


def test_custom_buckets_are_used_before_outlier_trimming_and_fitting():
    market = pd.DataFrame(
        {
            "year_numeric": [2020] * 6,
            "odometer_numeric": [180000, 185000, 190000, 200000, 210000, 290000],
            "price_numeric": [9000, 9000, 9000, 9000, 9000, 5000],
        }
    )
    buckets = [150000, 200000, 225000, 300000]

    prepared, trimmed = prepare_active_market_for_proposal(market, buckets=buckets)

    assert trimmed == 0
    assert set(prepared["km_bucket"]) == {200000, 300000}

    proposal, metadata = propose_curve_from_evidence(
        base_curve_tag="test_custom_buckets",
        active_market_df=market,
        anchor_years=[2020],
        buckets=buckets,
    )
    mid_by_bucket = proposal.set_index("km_bucket")["price_mid"]
    assert metadata.active_rows_trimmed == 0
    assert mid_by_bucket.loc[300000] < mid_by_bucket.loc[225000]
