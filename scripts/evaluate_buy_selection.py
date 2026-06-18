from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.data_loader import dataset_path


DEFAULT_OUT_DIR = Path("output") / "eval"


def _metric_value(value: float, has_evidence: bool) -> Any:
    return value if has_evidence else pd.NA


def _normalise_action(value: Any) -> str:
    return str(value or "").strip()


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
    valuation_rows: int,
    latest_valuation_rows: int,
    scored_rows: int,
    scored_with_actual_profit: int,
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
        "valuation_rows": int(valuation_rows),
        "latest_valuation_rows": int(latest_valuation_rows),
        "scored_rows": int(scored_rows),
        "scored_with_actual_profit": int(scored_with_actual_profit),
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
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valuations = pd.read_csv(valuations_path, low_memory=False)
    scored = pd.read_csv(scored_path, low_memory=False)
    valuation_rows = len(valuations)
    scored_rows = len(scored)

    if "url" not in valuations.columns:
        raise ValueError(f"{valuations_path} must include a url column")
    if "url" not in scored.columns:
        raise ValueError(f"{scored_path} must include a url column")
    if "actual_profit" not in scored.columns:
        raise ValueError(f"{scored_path} must include an actual_profit column")

    valuations = _latest_by_url(valuations)
    latest_valuation_rows = len(valuations)
    if "action_label" not in valuations.columns:
        valuations["action_label"] = ""

    scored = scored.copy()
    scored["actual_profit"] = pd.to_numeric(scored["actual_profit"], errors="coerce")
    scored = scored.dropna(subset=["actual_profit"])
    scored_with_actual_profit = len(scored)
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
        )
        if column in valuations.columns
    ]
    keep_scored_cols = [
        column
        for column in (
            "url",
            "actual_profit",
            "purchase_price",
            "actual_sale_price",
            "settled_date",
        )
        if column in scored.columns
    ]

    joined = valuations[keep_valuation_cols].merge(scored[keep_scored_cols], on="url", how="inner")
    joined["y_pred_buy"] = joined["action_label"].apply(lambda value: _normalise_action(value) == "Buy")
    joined["y_true_profitable"] = joined["actual_profit"] > 0

    if len(joined):
        status = "ok"
    elif scored_with_actual_profit == 0:
        status = "no_settled_actual_profit"
    elif latest_valuation_rows == 0:
        status = "no_valuation_rows"
    else:
        status = "no_url_overlap"

    metrics = pd.DataFrame(
        [
            _classification_metrics(
                joined,
                valuation_rows=valuation_rows,
                latest_valuation_rows=latest_valuation_rows,
                scored_rows=scored_rows,
                scored_with_actual_profit=scored_with_actual_profit,
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
    args = parser.parse_args(argv)

    joined, metrics = evaluate_buy_selection(
        valuations_path=args.valuations,
        scored_path=args.scored,
        out_dir=args.out_dir,
    )
    row = metrics.iloc[0].to_dict()
    if row["status"] != "ok":
        print(
            "[buy-selection] inconclusive: "
            f"status={row['status']} "
            f"valuation_rows={int(row['valuation_rows'])} "
            f"latest_valuation_rows={int(row['latest_valuation_rows'])} "
            f"scored_rows={int(row['scored_rows'])} "
            f"scored_with_actual_profit={int(row['scored_with_actual_profit'])} "
            f"joined_rows={int(row['rows'])}"
        )
        print(
            "[buy-selection] no precision/recall/f1 reported because there are no joined settled outcomes"
        )
        print(f"[buy-selection] wrote join: {args.out_dir / 'buy_selection_join.csv'}")
        print(f"[buy-selection] wrote metrics: {args.out_dir / 'buy_selection_classification.csv'}")
        return 2

    print(
        "[buy-selection] "
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
