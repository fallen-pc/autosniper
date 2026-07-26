from __future__ import annotations

import pandas as pd

from shared.sold_comparables import select_km_aware_comparables


def _rows(kms: list[int], prices: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"odometer_numeric": kms, "price_numeric": prices})


def test_prefers_comparables_within_50k_and_limits_to_nearest_rows() -> None:
    rows = _rows(
        [68_000, 80_000, 110_000, 180_000, 285_000],
        [9_400, 5_000, 3_550, 2_600, 809],
    )

    selected, stats = select_km_aware_comparables(rows, 75_000, max_samples=3)

    assert selected["odometer_numeric"].tolist() == [80_000, 68_000, 110_000]
    assert stats.method == "nearest_km"
    assert stats.count == 3
    assert stats.median == 5_000
    assert stats.km_max == 110_000


def test_expands_to_100k_when_preferred_window_is_too_thin() -> None:
    rows = _rows([50_000, 130_000, 160_000, 260_000], [8_000, 6_000, 5_000, 2_000])

    _, stats = select_km_aware_comparables(rows, 100_000)

    assert stats.method == "expanded_km"
    assert stats.count == 3
    assert stats.median == 6_000


def test_falls_back_to_full_pool_when_km_evidence_is_thin() -> None:
    rows = _rows([50_000, 250_000, 300_000], [8_000, 3_000, 2_000])

    _, stats = select_km_aware_comparables(rows, 100_000)

    assert stats.method == "tag_year_fallback"
    assert stats.count == 3
    assert stats.median == 3_000
