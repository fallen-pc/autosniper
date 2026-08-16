from __future__ import annotations

import pandas as pd

from scripts.build_lane_evidence import KM_GRID, km_bucket


def test_km_grid_matches_the_curve_grid() -> None:
    # curves.csv is built on these anchors; the evidence must group onto the same
    # points or the summary cannot inform a curve.
    assert KM_GRID == (30_000, 60_000, 100_000, 150_000, 200_000)


def test_km_maps_to_the_next_grid_point_at_or_above() -> None:
    assert km_bucket(0) == 30_000
    assert km_bucket(29_999) == 30_000
    assert km_bucket(30_000) == 30_000
    assert km_bucket(30_001) == 60_000
    assert km_bucket(95_000) == 100_000
    assert km_bucket(150_000) == 150_000


def test_high_km_collapses_into_the_top_bucket() -> None:
    # Everything above the grid lands in 200k, which is why that bucket pools a
    # 160k truck with a 300k one and shows a much wider spread.
    assert km_bucket(200_001) == 200_000
    assert km_bucket(350_000) == 200_000


def test_missing_odometer_yields_na_not_a_bucket() -> None:
    assert pd.isna(km_bucket(float("nan")))
    assert pd.isna(km_bucket(None))


def test_bucketing_a_series_keeps_every_row() -> None:
    values = pd.Series([10_000, 75_000, 210_000, float("nan")])
    buckets = values.apply(km_bucket)
    assert len(buckets) == len(values)
    assert list(buckets[:3]) == [30_000, 100_000, 200_000]
