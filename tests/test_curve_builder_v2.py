from __future__ import annotations

import pandas as pd

from shared.curve_builder_v2 import REQUIRED_KM_BUCKETS, propose_curve_from_evidence


def test_propose_curve_from_evidence_returns_full_grid_and_metadata():
    base_curve_tag = "mazda_3_bl_hatch_auto_petrol"
    active_df = pd.DataFrame(
        {
            "canonical_tag": [base_curve_tag] * 30,
            "year_numeric": ([2009] * 10) + ([2011] * 10) + ([2013] * 10),
            "price_numeric": [15000 - (index * 180) for index in range(30)],
            "odometer_numeric": [30000 + (index * 7000) for index in range(30)],
        }
    )

    proposed_df, metadata = propose_curve_from_evidence(
        base_curve_tag=base_curve_tag,
        active_market_df=active_df,
        sold_df=pd.DataFrame(),
        anchor_years=[2009, 2011, 2013],
    )

    assert len(proposed_df) == 15
    assert set(proposed_df["km_bucket"].tolist()) == set(REQUIRED_KM_BUCKETS)
    assert metadata.base_curve_tag == base_curve_tag
    assert metadata.active_rows_used == 30
    assert metadata.active_rows_trimmed == 0
    assert metadata.sold_rows_observed == 0


def test_propose_curve_from_evidence_is_monotone_by_km_and_year():
    base_curve_tag = "hyundai_i30_gd_hatch_auto_petrol"
    active_df = pd.DataFrame(
        {
            "canonical_tag": [base_curve_tag] * 45,
            "year_numeric": ([2013] * 15) + ([2015] * 15) + ([2016] * 15),
            "price_numeric": [18000 - (index * 120) for index in range(45)],
            "odometer_numeric": [25000 + ((index % 15) * 12000) for index in range(45)],
        }
    )

    proposed_df, _metadata = propose_curve_from_evidence(
        base_curve_tag=base_curve_tag,
        active_market_df=active_df,
        sold_df=pd.DataFrame(),
        anchor_years=[2013, 2015, 2016],
    )

    for anchor_year, subset in proposed_df.groupby("anchor_year", sort=True):
        mids = subset.sort_values("km_bucket")["price_mid"].tolist()
        assert all(current <= previous for previous, current in zip(mids, mids[1:])), anchor_year

    for km_bucket, subset in proposed_df.groupby("km_bucket", sort=True):
        mids = subset.sort_values("anchor_year")["price_mid"].tolist()
        assert all(current >= previous for previous, current in zip(mids, mids[1:])), km_bucket

    assert (proposed_df["price_low"] <= proposed_df["price_mid"]).all()
    assert (proposed_df["price_mid"] <= proposed_df["price_high"]).all()


def test_propose_curve_from_evidence_trims_extreme_active_outlier():
    base_curve_tag = "toyota_corolla_ascent-sport_zre182r_hatch_auto_petrol"
    active_df = pd.DataFrame(
        {
            "canonical_tag": [base_curve_tag] * 16,
            "year_numeric": [2016] * 16,
            "price_numeric": [22000, 21800, 22500, 21900, 22100, 21750, 22300, 22200, 21600, 22400, 22050, 21950, 21850, 22350, 22150, 99000],
            "odometer_numeric": [30000, 32000, 35000, 38000, 42000, 45000, 47000, 52000, 56000, 60000, 65000, 70000, 76000, 82000, 88000, 90000],
        }
    )

    proposed_df, metadata = propose_curve_from_evidence(
        base_curve_tag=base_curve_tag,
        active_market_df=active_df,
        sold_df=pd.DataFrame(),
        anchor_years=[2016],
    )

    row_30k = proposed_df[proposed_df["km_bucket"] == 30000].iloc[0]
    assert metadata.active_rows_trimmed >= 1
    assert row_30k["price_mid"] < 30000


def test_propose_curve_from_evidence_derives_default_anchors_and_counts_valid_sold_rows():
    base_curve_tag = "mazda_3_bl_hatch_auto_petrol"
    active_df = pd.DataFrame(
        {
            "canonical_tag": [base_curve_tag] * 19,
            "year_numeric": ([2009] * 6) + ([2011] * 6) + ([2013] * 6) + ["bad-year"],
            "price_numeric": (
                [16000, 15500, 15000, 14500, 14000, 13500]
                + [17000, 16500, 16000, 15500, 15000, 14500]
                + [18000, 17500, 17000, 16500, 16000, 15500]
                + [99999]
            ),
            "odometer_numeric": (
                [30000, 60000, 100000, 150000, 200000, 100000]
                + [30000, 60000, 100000, 150000, 200000, 100000]
                + [30000, 60000, 100000, 150000, 200000, 100000]
                + ["bad-km"]
            ),
        }
    )
    sold_df = pd.DataFrame(
        {
            "year_numeric": [2010, 2012, "bad-year"],
            "price_numeric": [12000, 13000, 14000],
            "odometer_numeric": [80000, 90000, None],
        }
    )

    proposed_df, metadata = propose_curve_from_evidence(
        base_curve_tag=base_curve_tag,
        active_market_df=active_df,
        sold_df=sold_df,
    )

    assert metadata.anchor_years == [2009, 2011, 2013]
    assert metadata.active_rows_used == 18
    assert metadata.sold_rows_observed == 2
    assert len(proposed_df) == 15
