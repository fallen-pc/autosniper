from __future__ import annotations

import pandas as pd

from scripts.backfill_ai_repair_estimates import backfill_repair_estimates


def test_backfills_missing_repair_range_from_source_condition() -> None:
    valuations = pd.DataFrame(
        [
            {
                "url": "https://example.test/car-1",
                "analysis_context": "sold_simulated",
                "computed_verdict": "Conditional Flip",
                "repair_estimate": pd.NA,
                "repair_estimate_low": pd.NA,
                "repair_estimate_high": pd.NA,
                "repair_estimate_low_value": pd.NA,
                "repair_estimate_high_value": pd.NA,
            }
        ]
    )

    updated, report = backfill_repair_estimates(
        valuations,
        condition_by_url={
            "https://example.test/car-1": "windscreen chipped or cracked.\nlarge scuff on panel",
        },
    )

    assert len(report) == 1
    assert report.iloc[0]["repair_backfill_source"] == "source_general_condition"
    assert updated.loc[0, "repair_estimate_low_value"] > 0
    assert updated.loc[0, "repair_estimate_high_value"] >= updated.loc[0, "repair_estimate_low_value"]
    assert str(updated.loc[0, "repair_estimate_high"]).startswith("$")


def test_backfills_hard_avoid_range_from_existing_repair_estimate_when_condition_missing() -> None:
    valuations = pd.DataFrame(
        [
            {
                "url": "https://example.test/car-2",
                "analysis_context": "active",
                "computed_verdict": "Avoid",
                "repair_estimate": "$10,000",
                "repair_estimate_low": pd.NA,
                "repair_estimate_high": pd.NA,
                "repair_estimate_low_value": pd.NA,
                "repair_estimate_high_value": pd.NA,
            }
        ]
    )

    updated, report = backfill_repair_estimates(valuations, condition_by_url={})

    assert len(report) == 1
    assert report.iloc[0]["repair_backfill_source"] == "repair_estimate_fallback"
    assert updated.loc[0, "repair_estimate_low"] == "$10,000"
    assert updated.loc[0, "repair_estimate_high"] == "$10,000"
    assert updated.loc[0, "repair_estimate_low_value"] == 10000
    assert updated.loc[0, "repair_estimate_high_value"] == 10000


def test_preserves_existing_repair_range_values() -> None:
    valuations = pd.DataFrame(
        [
            {
                "url": "https://example.test/car-3",
                "analysis_context": "active",
                "computed_verdict": "Review",
                "repair_estimate": "$900",
                "repair_estimate_low": "$800",
                "repair_estimate_high": "$1,200",
                "repair_estimate_low_value": 800,
                "repair_estimate_high_value": 1200,
            }
        ]
    )

    updated, report = backfill_repair_estimates(
        valuations,
        condition_by_url={"https://example.test/car-3": "engine noise observed."},
    )

    assert report.empty
    assert updated.loc[0, "repair_estimate_low_value"] == 800
    assert updated.loc[0, "repair_estimate_high_value"] == 1200
