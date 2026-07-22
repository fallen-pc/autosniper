import pandas as pd

from shared.buying_lanes import (
    ALL_CAPITAL_LANES,
    FIRST_BUY_LANE,
    HIGHER_CAPITAL_LANE,
    SPECIALIST_CAPITAL_LANE,
    UNKNOWN_CAPITAL_LANE,
    classify_capital_lane,
    filter_capital_lane,
)


def test_classify_capital_lane_boundaries() -> None:
    assert classify_capital_lane(None) == UNKNOWN_CAPITAL_LANE
    assert classify_capital_lane(0) == UNKNOWN_CAPITAL_LANE
    assert classify_capital_lane(19_999) == FIRST_BUY_LANE
    assert classify_capital_lane(20_000) == HIGHER_CAPITAL_LANE
    assert classify_capital_lane(40_000) == HIGHER_CAPITAL_LANE
    assert classify_capital_lane(40_001) == SPECIALIST_CAPITAL_LANE


def test_filter_capital_lane_preserves_all_or_selects_exact_lane() -> None:
    frame = pd.DataFrame(
        {
            "url": ["first", "higher", "specialist"],
            "capital_lane": [FIRST_BUY_LANE, HIGHER_CAPITAL_LANE, SPECIALIST_CAPITAL_LANE],
        }
    )

    assert filter_capital_lane(frame, ALL_CAPITAL_LANES)["url"].tolist() == [
        "first",
        "higher",
        "specialist",
    ]
    assert filter_capital_lane(frame, HIGHER_CAPITAL_LANE)["url"].tolist() == ["higher"]
