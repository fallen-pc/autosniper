from __future__ import annotations

import pandas as pd

from scripts.build_replay_outcomes import (
    KM_TOLERANCE_PCT,
    MIN_RETAIL_MATCHES,
    YEAR_TOLERANCE,
    retail_estimate_for,
)


def _lane(rows):
    return pd.DataFrame(rows)


def _obs(year, odo, price):
    return {"year": year, "odometer": odo, "final_asking_price": price}


def test_median_of_matching_observations() -> None:
    lane = _lane([_obs(2018, 100_000, p) for p in (20_000, 22_000, 24_000, 26_000, 28_000)])
    estimate, n = retail_estimate_for(lane, 2018, 100_000)
    assert estimate == 24_000
    assert n == 5


def test_thin_lane_returns_no_estimate() -> None:
    # Fewer than MIN_RETAIL_MATCHES must yield None, never a guess off 1-2 cars.
    lane = _lane([_obs(2018, 100_000, 20_000), _obs(2018, 100_000, 22_000)])
    estimate, n = retail_estimate_for(lane, 2018, 100_000)
    assert estimate is None
    assert n == 2


def test_empty_lane_returns_no_estimate() -> None:
    assert retail_estimate_for(pd.DataFrame(), 2018, 100_000) == (None, 0)


def test_year_outside_tolerance_is_excluded() -> None:
    near = [_obs(2018, 100_000, 20_000) for _ in range(5)]
    far = [_obs(2005, 100_000, 90_000) for _ in range(5)]
    estimate, n = retail_estimate_for(_lane(near + far), 2018, 100_000)
    assert n == 5
    assert estimate == 20_000


def test_year_at_the_tolerance_edge_is_included() -> None:
    lane = _lane([_obs(2018 + YEAR_TOLERANCE, 100_000, 30_000) for _ in range(5)])
    estimate, n = retail_estimate_for(lane, 2018, 100_000)
    assert n == 5
    assert estimate == 30_000


def test_odometer_outside_tolerance_is_excluded() -> None:
    # A 250k car must not price a 100k one - that is the whole point of matching
    # rather than taking a flat per-lane median.
    near = [_obs(2018, 100_000, 25_000) for _ in range(5)]
    far = [_obs(2018, 250_000, 8_000) for _ in range(5)]
    estimate, n = retail_estimate_for(_lane(near + far), 2018, 100_000)
    assert n == 5
    assert estimate == 25_000


def test_odometer_tolerance_is_proportional() -> None:
    inside = 100_000 * (1 + KM_TOLERANCE_PCT) - 1
    lane = _lane([_obs(2018, inside, 21_000) for _ in range(5)])
    estimate, n = retail_estimate_for(lane, 2018, 100_000)
    assert n == 5
    assert estimate == 21_000


def test_zero_and_missing_prices_do_not_count_as_matches() -> None:
    lane = _lane(
        [_obs(2018, 100_000, 0) for _ in range(3)]
        + [_obs(2018, 100_000, None) for _ in range(3)]
        + [_obs(2018, 100_000, 20_000) for _ in range(2)]
    )
    estimate, n = retail_estimate_for(lane, 2018, 100_000)
    assert n == 2
    assert estimate is None


def test_missing_km_skips_only_the_km_filter() -> None:
    lane = _lane([_obs(2018, 100_000, 20_000) for _ in range(5)])
    estimate, n = retail_estimate_for(lane, 2018, None)
    assert n == 5
    assert estimate == 20_000


def test_min_matches_constant_is_not_permissive() -> None:
    assert MIN_RETAIL_MATCHES >= 5
