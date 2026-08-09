"""Shared capital-lane labels for operator buying screens.

The lane is descriptive only. It does not change valuation, proxy-max, repair,
or action-policy rules.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


FIRST_BUY_RESALE_CEILING = 20_000.0
HIGHER_CAPITAL_RESALE_CEILING = 40_000.0

ALL_CAPITAL_LANES = "All capital lanes"
FIRST_BUY_LANE = "First-buy (<$20k resale)"
HIGHER_CAPITAL_LANE = "Higher-capital ($20k-$40k resale)"
SPECIALIST_CAPITAL_LANE = "Specialist (>$40k resale)"
UNKNOWN_CAPITAL_LANE = "Unpriced / review"

CAPITAL_LANE_OPTIONS = (
    ALL_CAPITAL_LANES,
    FIRST_BUY_LANE,
    HIGHER_CAPITAL_LANE,
    SPECIALIST_CAPITAL_LANE,
    UNKNOWN_CAPITAL_LANE,
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric) or numeric <= 0:
        return None
    return numeric


def classify_capital_lane(resale_value: Any) -> str:
    """Return the operator lane for a curve-governed resale value."""

    resale = _number(resale_value)
    if resale is None:
        return UNKNOWN_CAPITAL_LANE
    if resale < FIRST_BUY_RESALE_CEILING:
        return FIRST_BUY_LANE
    if resale <= HIGHER_CAPITAL_RESALE_CEILING:
        return HIGHER_CAPITAL_LANE
    return SPECIALIST_CAPITAL_LANE


def filter_capital_lane(
    frame: pd.DataFrame,
    lane: str,
    *,
    lane_column: str = "capital_lane",
) -> pd.DataFrame:
    """Filter a prepared buying-screen frame without changing row decisions."""

    if frame.empty or lane == ALL_CAPITAL_LANES:
        return frame.copy()
    if lane_column not in frame.columns:
        return frame.iloc[0:0].copy()
    return frame[frame[lane_column] == lane].copy()
