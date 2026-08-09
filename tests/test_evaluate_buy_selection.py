from __future__ import annotations

import pandas as pd

from scripts.evaluate_buy_selection import evaluate_buy_selection
from scripts.generate_simulated_sold_outcomes import generate_simulated_sold_outcomes


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


def test_generate_simulated_outcomes_marks_proxy_profit(tmp_path) -> None:
    valuations_path = tmp_path / "ai_listing_valuations.csv"
    scored_path = tmp_path / "scored_listings_enriched.csv"
    output_path = tmp_path / "simulated_sold_outcomes.csv"

    pd.DataFrame(
        [
            {
                "url": "sim-buy",
                "analysis_timestamp": "2026-06-01T01:00:00Z",
                "action_label": "Buy",
                "resale_mid_value": 15000,
            },
        ]
    ).to_csv(valuations_path, index=False)
    pd.DataFrame(
        [
            {
                "url": "sim-buy",
                "purchase_price": 10000,
                "actual_fees_total": 500,
                "reconditioning_cost": 700,
            },
        ]
    ).to_csv(scored_path, index=False)

    output = generate_simulated_sold_outcomes(
        valuations_path=valuations_path,
        scored_path=scored_path,
        output_path=output_path,
    )

    row = output.iloc[0]
    assert row["outcome_type"] == "simulated"
    assert row["simulated_source"] == "resale_mid_value"
    assert row["simulated_sale_price"] == 15000
    assert row["simulated_actual_profit"] == 3800
    assert "not a real sale" in row["outcome_note"]
    assert output_path.exists()


def test_evaluate_buy_selection_can_use_simulated_profit_column(tmp_path) -> None:
    valuations_path = tmp_path / "ai_listing_valuations.csv"
    scored_path = tmp_path / "simulated_sold_outcomes.csv"
    out_dir = tmp_path / "eval"

    pd.DataFrame(
        [
            {"url": "buy-good", "action_label": "Buy"},
            {"url": "watch-good", "action_label": "Watch"},
        ]
    ).to_csv(valuations_path, index=False)
    pd.DataFrame(
        [
            {
                "url": "buy-good",
                "simulated_actual_profit": 1200,
                "outcome_type": "simulated",
            },
            {
                "url": "watch-good",
                "simulated_actual_profit": 900,
                "outcome_type": "simulated",
            },
        ]
    ).to_csv(scored_path, index=False)

    joined, metrics = evaluate_buy_selection(
        valuations_path=valuations_path,
        scored_path=scored_path,
        out_dir=out_dir,
        benchmark_type="simulated",
        profit_column="simulated_actual_profit",
    )

    row = metrics.iloc[0]
    assert len(joined) == 2
    assert row["status"] == "ok"
    assert row["benchmark_type"] == "simulated"
    assert row["profit_column"] == "simulated_actual_profit"
    assert row["true_positive"] == 1
    assert row["false_negative"] == 1
    assert row["precision"] == 1.0
    assert row["recall"] == 0.5


def test_evaluate_buy_selection_can_use_computed_verdict_proxy(tmp_path) -> None:
    valuations_path = tmp_path / "ai_listing_valuations.csv"
    scored_path = tmp_path / "simulated_sold_outcomes.csv"
    out_dir = tmp_path / "eval"

    pd.DataFrame(
        [
            {"url": "flip-good", "computed_verdict": "Conditional Flip"},
            {"url": "avoid-bad", "computed_verdict": "Avoid"},
            {"url": "avoid-good", "computed_verdict": "Avoid"},
        ]
    ).to_csv(valuations_path, index=False)
    pd.DataFrame(
        [
            {"url": "flip-good", "simulated_actual_profit": 1200},
            {"url": "avoid-bad", "simulated_actual_profit": -100},
            {"url": "avoid-good", "simulated_actual_profit": 900},
        ]
    ).to_csv(scored_path, index=False)

    joined, metrics = evaluate_buy_selection(
        valuations_path=valuations_path,
        scored_path=scored_path,
        out_dir=out_dir,
        benchmark_type="simulated",
        profit_column="simulated_actual_profit",
        prediction_source="computed_verdict",
    )

    row = metrics.iloc[0]
    assert len(joined) == 3
    assert row["prediction_source"] == "computed_verdict"
    assert "Conditional Flip" in row["positive_labels"]
    assert row["true_positive"] == 1
    assert row["true_negative"] == 1
    assert row["false_negative"] == 1
    assert row["precision"] == 1.0
    assert row["recall"] == 0.5


def test_evaluate_buy_selection_keeps_comps_informational(tmp_path) -> None:
    valuations_path = tmp_path / "ai_listing_valuations.csv"
    scored_path = tmp_path / "simulated_sold_outcomes.csv"
    out_dir = tmp_path / "eval"

    pd.DataFrame(
        [
            {
                "url": "thin-comps-profit",
                "action_label": "Buy",
                "computed_verdict": "Conditional Flip",
                "bid_status": "Cheap",
                "hard_max_safety": "Strong",
                "expected_auction_worst_profit_value": 3000,
                "profit_at_current_bid_worst_value": 3000,
                "expected_auction_comps_count": 1,
            },
        ]
    ).to_csv(valuations_path, index=False)
    pd.DataFrame(
        [
            {"url": "thin-comps-profit", "simulated_actual_profit": 2000},
        ]
    ).to_csv(scored_path, index=False)

    joined, metrics = evaluate_buy_selection(
        valuations_path=valuations_path,
        scored_path=scored_path,
        out_dir=out_dir,
        benchmark_type="simulated",
        profit_column="simulated_actual_profit",
        prediction_source="action",
    )

    assert joined.iloc[0]["resolved_action_label"] == "Buy"
    assert joined.iloc[0]["prediction_label"] == "Buy"
    assert joined.iloc[0]["policy_resolution_status"] == "resolved_current_policy"
    assert metrics.iloc[0]["buy_predictions"] == 1
    assert metrics.iloc[0]["false_negative"] == 0


def test_evaluate_buy_selection_reports_missing_policy_inputs_without_nan_fallback(tmp_path) -> None:
    valuations_path = tmp_path / "ai_listing_valuations.csv"
    scored_path = tmp_path / "simulated_sold_outcomes.csv"
    out_dir = tmp_path / "eval"

    pd.DataFrame(
        [
            {
                "url": "missing-policy-inputs",
                "action_label": None,
                "computed_verdict": "Avoid",
            },
        ]
    ).to_csv(valuations_path, index=False)
    pd.DataFrame(
        [
            {"url": "missing-policy-inputs", "simulated_actual_profit": 2000},
        ]
    ).to_csv(scored_path, index=False)

    joined, metrics = evaluate_buy_selection(
        valuations_path=valuations_path,
        scored_path=scored_path,
        out_dir=out_dir,
        benchmark_type="simulated",
        profit_column="simulated_actual_profit",
        prediction_source="action",
    )

    assert joined.iloc[0]["resolved_action_label"] == "Review"
    assert joined.iloc[0]["policy_resolution_status"] == "missing_policy_inputs"
    assert joined.iloc[0]["missing_policy_inputs"] == "bid_status|hard_max_safety"
    assert metrics.iloc[0]["unresolved_policy_rows"] == 1
    assert metrics.iloc[0]["stored_action_fallback_rows"] == 0


def test_evaluate_buy_selection_carries_scored_policy_resolution_fields(tmp_path) -> None:
    valuations_path = tmp_path / "ai_listing_valuations.csv"
    scored_path = tmp_path / "simulated_retail_median_outcomes.csv"
    out_dir = tmp_path / "eval"

    pd.DataFrame(
        [
            {
                "url": "retail-profit",
                "action_label": "",
                "computed_verdict": "Conditional Flip",
                "bid_status": "Cheap",
                "hard_max_safety": "Strong",
                "expected_auction_worst_profit_value": 3000,
                "profit_at_current_bid_worst_value": 3000,
                "expected_auction_comps_count": 4,
            },
        ]
    ).to_csv(valuations_path, index=False)
    pd.DataFrame(
        [
            {
                "url": "retail-profit",
                "simulated_profit": 2000,
                "action_label": "",
                "resolved_action_label": "",
                "action_label_display": "Missing policy inputs",
                "policy_resolution_status": "missing_policy_inputs",
                "missing_policy_inputs": "bid_status|hard_max_safety",
            },
        ]
    ).to_csv(scored_path, index=False)

    joined, metrics = evaluate_buy_selection(
        valuations_path=valuations_path,
        scored_path=scored_path,
        out_dir=out_dir,
        benchmark_type="simulated",
        profit_column="simulated_profit",
        prediction_source="action",
    )

    row = joined.iloc[0]
    assert row["resolved_action_label"] == "Buy"
    assert row["policy_resolution_status"] == "resolved_current_policy"
    assert row["scored_action_label_display"] == "Missing policy inputs"
    assert row["scored_policy_resolution_status"] == "missing_policy_inputs"
    assert row["scored_missing_policy_inputs"] == "bid_status|hard_max_safety"
    assert metrics.iloc[0]["unresolved_policy_rows"] == 0
    assert metrics.iloc[0]["scored_unresolved_policy_rows"] == 1
