from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.decision_policy import BUYABLE_VERDICTS, derive_action_label_from_row
from shared.data_loader import dataset_path


DEFAULT_OUT_DIR = Path("output") / "eval"
DEFAULT_MIN_PROFIT = 1500.0


def _metric_value(value: float, has_evidence: bool) -> Any:
    return value if has_evidence else pd.NA


def _normalise_action(value: Any) -> str:
    return str(value or "").strip()


def _normalise_label_set(values: list[str] | tuple[str, ...] | None) -> set[str]:
    if values:
        return {str(value).strip() for value in values if str(value).strip()}
    return set()


def _latest_by_url(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "url" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    working = df.copy()
    if "analysis_timestamp" in working.columns:
        working["analysis_timestamp"] = pd.to_datetime(working["analysis_timestamp"], errors="coerce")
        working = working.sort_values("analysis_timestamp")
    return working.drop_duplicates(subset=["url"], keep="last")


def _classification_metrics(
    joined: pd.DataFrame,
    *,
    benchmark_type: str,
    profit_column: str,
    prediction_source: str,
    positive_labels: set[str],
    valuation_rows: int,
    latest_valuation_rows: int,
    scored_rows: int,
    scored_with_profit: int,
    status: str,
) -> dict[str, float | int | str | Any]:
    y_pred = joined["y_pred_buy"].astype(bool)
    y_true = joined["y_true_profitable"].astype(bool)
    has_evidence = bool(len(joined))

    tp = int((y_pred & y_true).sum())
    fp = int((y_pred & ~y_true).sum())
    tn = int((~y_pred & ~y_true).sum())
    fn = int((~y_pred & y_true).sum())

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    accuracy = (tp + tn) / len(joined) if len(joined) else 0.0

    return {
        "status": status,
        "benchmark_type": benchmark_type,
        "profit_column": profit_column,
        "prediction_source": prediction_source,
        "positive_labels": "|".join(sorted(positive_labels)),
        "valuation_rows": int(valuation_rows),
        "latest_valuation_rows": int(latest_valuation_rows),
        "scored_rows": int(scored_rows),
        "scored_with_actual_profit": int(scored_with_profit),
        "scored_with_profit": int(scored_with_profit),
        "rows": int(len(joined)),
        "buy_predictions": int(y_pred.sum()),
        "profitable_actuals": int(y_true.sum()),
        "true_positive": tp,
        "false_positive": fp,
        "true_negative": tn,
        "false_negative": fn,
        "precision": _metric_value(precision, has_evidence),
        "recall": _metric_value(recall, has_evidence),
        "f1": _metric_value(f1, has_evidence),
        "accuracy": _metric_value(accuracy, has_evidence),
    }


def evaluate_buy_selection(
    *,
    valuations_path: Path,
    scored_path: Path,
    out_dir: Path,
    benchmark_type: str = "actual",
    profit_column: str = "actual_profit",
    prediction_source: str = "action",
    positive_labels: list[str] | tuple[str, ...] | None = None,
    min_profit: float = DEFAULT_MIN_PROFIT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valuations = pd.read_csv(valuations_path, low_memory=False)
    scored = pd.read_csv(scored_path, low_memory=False)
    valuation_rows = len(valuations)
    scored_rows = len(scored)

    if "url" not in valuations.columns:
        raise ValueError(f"{valuations_path} must include a url column")
    if "url" not in scored.columns:
        raise ValueError(f"{scored_path} must include a url column")
    if profit_column not in scored.columns:
        raise ValueError(f"{scored_path} must include a {profit_column} column")

    valuations = _latest_by_url(valuations)
    latest_valuation_rows = len(valuations)
    if "action_label" not in valuations.columns:
        valuations["action_label"] = ""

    scored = scored.copy()
    scored[profit_column] = pd.to_numeric(scored[profit_column], errors="coerce")
    scored = scored.dropna(subset=[profit_column])
    scored_with_profit = len(scored)
    scored = scored.drop_duplicates(subset=["url"], keep="last")

    keep_valuation_cols = [
        column
        for column in (
            "url",
            "analysis_timestamp",
            "action_label",
            "computed_verdict",
            "bid_status",
            "recommended_max_bid",
            "recommended_max_bid_value",
            "expected_auction_profit",
            "expected_auction_profit_value",
            "expected_auction_worst_profit",
            "expected_auction_worst_profit_value",
            "profit_at_current_bid_worst",
            "profit_at_current_bid_worst_value",
            "hard_max_safety",
        )
        if column in valuations.columns
    ]
    keep_scored_cols = list(
        dict.fromkeys(
            column
            for column in (
                "url",
                profit_column,
                "actual_profit",
                "simulated_actual_profit",
                "simulated_sale_price",
                "simulated_source",
                "outcome_type",
                "purchase_price",
                "actual_sale_price",
                "settled_date",
            )
            if column in scored.columns
        )
    )

    joined = valuations[keep_valuation_cols].merge(scored[keep_scored_cols], on="url", how="inner")
    joined["benchmark_type"] = benchmark_type
    joined["profit_column"] = profit_column
    joined["benchmark_profit"] = joined[profit_column]
    if prediction_source == "computed_verdict":
        label_set = _normalise_label_set(positive_labels) or set(BUYABLE_VERDICTS)
        joined["prediction_label"] = joined["computed_verdict"].apply(_normalise_action)
    elif prediction_source == "action":
        label_set = _normalise_label_set(positive_labels) or {"Buy"}
        joined["prediction_label"] = pd.NA
    else:
        raise ValueError("prediction_source must be 'action' or 'computed_verdict'")

    joined["resolved_action_label"] = joined.apply(
        lambda row: derive_action_label_from_row(
            row,
            min_profit=min_profit,
            fallback=_normalise_action(row.get("action_label")),
        ),
        axis=1,
    )
    if prediction_source == "action":
        joined["prediction_label"] = joined["resolved_action_label"].apply(_normalise_action)
    joined["prediction_source"] = prediction_source
    joined["positive_labels"] = "|".join(sorted(label_set))
    joined["y_pred_buy"] = joined["prediction_label"].apply(lambda value: _normalise_action(value) in label_set)
    joined["y_true_profitable"] = joined["benchmark_profit"] > 0

    if len(joined):
        status = "ok"
    elif scored_with_profit == 0:
        status = "no_settled_actual_profit" if benchmark_type == "actual" else "no_simulated_profit"
    elif latest_valuation_rows == 0:
        status = "no_valuation_rows"
    else:
        status = "no_url_overlap"

    metrics = pd.DataFrame(
        [
            _classification_metrics(
                joined,
                benchmark_type=benchmark_type,
                profit_column=profit_column,
                prediction_source=prediction_source,
                positive_labels=label_set,
                valuation_rows=valuation_rows,
                latest_valuation_rows=latest_valuation_rows,
                scored_rows=scored_rows,
                scored_with_profit=scored_with_profit,
                status=status,
            )
        ]
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(joined, out_dir / "buy_selection_join.csv", index=False)
    write_dataframe_csv_atomic(metrics, out_dir / "buy_selection_classification.csv", index=False)
    return joined, metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate whether AI Analysis Buy actions matched profitable settled outcomes."
    )
    parser.add_argument("--valuations", type=Path, default=dataset_path("ai_listing_valuations.csv"))
    parser.add_argument("--scored", type=Path, default=dataset_path("scored_listings_enriched.csv"))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--benchmark-type",
        choices=("actual", "simulated"),
        default="actual",
        help="Label the evaluation as real settled evidence or simulated proxy evidence.",
    )
    parser.add_argument(
        "--profit-column",
        default="actual_profit",
        help="Numeric profit column to evaluate; use simulated_actual_profit for simulated outcomes.",
    )
    parser.add_argument(
        "--prediction-source",
        choices=("action", "computed_verdict"),
        default="action",
        help="Use resolved action labels or buyable computed verdicts as the positive selection signal.",
    )
    parser.add_argument(
        "--positive-label",
        action="append",
        default=None,
        help="Positive label for the selected prediction source. Repeat to pass multiple labels.",
    )
    parser.add_argument(
        "--min-profit",
        type=float,
        default=DEFAULT_MIN_PROFIT,
        help="Minimum profit used when resolving missing/stale action labels through the shared decision policy.",
    )
    args = parser.parse_args(argv)

    joined, metrics = evaluate_buy_selection(
        valuations_path=args.valuations,
        scored_path=args.scored,
        out_dir=args.out_dir,
        benchmark_type=args.benchmark_type,
        profit_column=args.profit_column,
        prediction_source=args.prediction_source,
        positive_labels=args.positive_label,
        min_profit=args.min_profit,
    )
    row = metrics.iloc[0].to_dict()
    if row["status"] != "ok":
        print(
            "[buy-selection] inconclusive: "
            f"status={row['status']} "
            f"benchmark_type={row['benchmark_type']} "
            f"profit_column={row['profit_column']} "
            f"prediction_source={row['prediction_source']} "
            f"valuation_rows={int(row['valuation_rows'])} "
            f"latest_valuation_rows={int(row['latest_valuation_rows'])} "
            f"scored_rows={int(row['scored_rows'])} "
            f"scored_with_profit={int(row['scored_with_profit'])} "
            f"joined_rows={int(row['rows'])}"
        )
        print(
            "[buy-selection] no precision/recall/f1 reported because there are no joined profit outcomes"
        )
        print(f"[buy-selection] wrote join: {args.out_dir / 'buy_selection_join.csv'}")
        print(f"[buy-selection] wrote metrics: {args.out_dir / 'buy_selection_classification.csv'}")
        return 2

    print(
        "[buy-selection] "
        f"benchmark_type={row['benchmark_type']} "
        f"prediction_source={row['prediction_source']} "
        f"rows={int(row['rows'])} "
        f"buy_predictions={int(row['buy_predictions'])} "
        f"profitable_actuals={int(row['profitable_actuals'])} "
        f"precision={row['precision']:.3f} "
        f"recall={row['recall']:.3f} "
        f"f1={row['f1']:.3f}"
    )
    print(f"[buy-selection] wrote join: {args.out_dir / 'buy_selection_join.csv'}")
    print(f"[buy-selection] wrote metrics: {args.out_dir / 'buy_selection_classification.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
