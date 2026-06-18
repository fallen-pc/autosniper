from __future__ import annotations

import pandas as pd

from scripts.evaluate_buy_selection import evaluate_buy_selection


def test_evaluate_buy_selection_writes_buy_profit_metrics(tmp_path) -> None:
    valuations_path = tmp_path / "ai_listing_valuations.csv"
    scored_path = tmp_path / "scored_listings_enriched.csv"
    out_dir = tmp_path / "eval"

    pd.DataFrame(
        [
            {
                "url": "buy-good",
                "analysis_timestamp": "2026-06-01T01:00:00Z",
                "action_label": "Buy",
                "computed_verdict": "Conditional Flip",
            },
            {
                "url": "buy-bad",
                "analysis_timestamp": "2026-06-01T01:00:00Z",
                "action_label": "Buy",
                "computed_verdict": "Conditional Flip",
            },
            {
                "url": "watch-good",
                "analysis_timestamp": "2026-06-01T01:00:00Z",
                "action_label": "Watch",
                "computed_verdict": "Marginal (repairs)",
            },
            {
                "url": "watch-bad",
                "analysis_timestamp": "2026-06-01T01:00:00Z",
                "action_label": "Watch",
                "computed_verdict": "Avoid",
            },
        ]
    ).to_csv(valuations_path, index=False)
    pd.DataFrame(
        [
            {"url": "buy-good", "actual_profit": 1200},
            {"url": "buy-bad", "actual_profit": -500},
            {"url": "watch-good", "actual_profit": 900},
            {"url": "watch-bad", "actual_profit": -100},
        ]
    ).to_csv(scored_path, index=False)

    joined, metrics = evaluate_buy_selection(
        valuations_path=valuations_path,
        scored_path=scored_path,
        out_dir=out_dir,
    )

    row = metrics.iloc[0]
    assert len(joined) == 4
    assert row["true_positive"] == 1
    assert row["false_positive"] == 1
    assert row["true_negative"] == 1
    assert row["false_negative"] == 1
    assert row["precision"] == 0.5
    assert row["recall"] == 0.5
    assert row["f1"] == 0.5
    assert (out_dir / "buy_selection_join.csv").exists()
    assert (out_dir / "buy_selection_classification.csv").exists()


def test_evaluate_buy_selection_marks_missing_actual_profit_inconclusive(tmp_path) -> None:
    valuations_path = tmp_path / "ai_listing_valuations.csv"
    scored_path = tmp_path / "scored_listings_enriched.csv"
    out_dir = tmp_path / "eval"

    pd.DataFrame(
        [
            {
                "url": "active-buy",
                "analysis_timestamp": "2026-06-01T01:00:00Z",
                "action_label": "Buy",
            },
        ]
    ).to_csv(valuations_path, index=False)
    pd.DataFrame(
        [
            {"url": "active-buy", "actual_profit": pd.NA},
            {"url": "settled-other", "actual_profit": pd.NA},
        ]
    ).to_csv(scored_path, index=False)

    joined, metrics = evaluate_buy_selection(
        valuations_path=valuations_path,
        scored_path=scored_path,
        out_dir=out_dir,
    )

    row = metrics.iloc[0]
    assert joined.empty
    assert row["status"] == "no_settled_actual_profit"
    assert row["valuation_rows"] == 1
    assert row["scored_rows"] == 2
    assert row["scored_with_actual_profit"] == 0
    assert pd.isna(row["precision"])
    assert pd.isna(row["recall"])
    assert pd.isna(row["f1"])
