from __future__ import annotations

import pandas as pd

from shared.calibration import classify_calibration_row, summarize_calibration


def test_classify_calibration_row_marks_profitable_within_bid() -> None:
    row = pd.Series(
        {
            "sold_price": 10_000,
            "max_bid": 12_000,
            "curve_estimate": 18_000,
            "curve_high": 19_000,
            "projected_profit_at_sold": 3_000,
        }
    )

    assert classify_calibration_row(row) == "profitable within bid"


def test_classify_calibration_row_marks_overbid_risk() -> None:
    row = pd.Series(
        {
            "sold_price": 10_000,
            "max_bid": 12_000,
            "curve_estimate": 11_000,
            "curve_high": 12_000,
            "projected_profit_at_sold": -500,
        }
    )

    assert classify_calibration_row(row) == "overbid risk"


def test_classify_calibration_row_marks_too_conservative() -> None:
    row = pd.Series(
        {
            "sold_price": 10_000,
            "max_bid": 9_000,
            "curve_estimate": 15_000,
            "curve_high": 16_000,
            "projected_profit_at_sold": 2_000,
            "delta_pct": 33.3,
            "repair_cost_estimate": 0,
            "risk_buffer": 0,
        }
    )

    assert classify_calibration_row(row) == "curve too conservative"


def test_summarize_calibration_counts_core_groups() -> None:
    detail = pd.DataFrame(
        [
            {
                "spec_reason": "",
                "would_win": True,
                "projected_profit_at_sold": 3000,
                "calibration_reason": "profitable within bid",
            },
            {
                "spec_reason": "",
                "would_win": True,
                "projected_profit_at_sold": -100,
                "calibration_reason": "overbid risk",
            },
            {
                "spec_reason": "",
                "would_win": False,
                "projected_profit_at_sold": 2000,
                "calibration_reason": "curve too conservative",
            },
            {
                "spec_reason": "NOT_COVERED",
                "would_win": False,
                "projected_profit_at_sold": None,
                "calibration_reason": "not covered",
            },
        ]
    )

    summary = summarize_calibration(detail)

    assert summary["total_rows"] == 4
    assert summary["covered_rows"] == 3
    assert summary["not_covered_rows"] == 1
    assert summary["profitable_within_bid_rows"] == 1
    assert summary["overbid_risk_rows"] == 1
    assert summary["priced_out_profitable_rows"] == 1
    assert summary["total_profitable_within_bid"] == 3000
