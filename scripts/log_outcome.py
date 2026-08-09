"""Log a real purchase/flip outcome into the outcome-tracking loop.

Usage (from repo root):

    python scripts/log_outcome.py --url <listing_url> --sale-price 18500 \
        --fees 640 --recond 350 [--purchase-price 12800] [--date 2026-07-04]

This fills the manual "actuals" columns on the matching row in
CSV_data/model_audit/scored_listings.csv, regenerates the accuracy metric
files, and prints predicted-vs-actual so each logged flip immediately shows
how well the valuation model did.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd

import ops.outcome_tracking as outcome_tracking
from scripts.atomic_csv import write_dataframe_csv_atomic


def _fmt(value: object) -> str:
    try:
        if value is None or pd.isna(value):
            return "n/a"
    except (TypeError, ValueError):
        pass
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def log_outcome(
    url: str,
    sale_price: float,
    fees: float = 0.0,
    recond: float = 0.0,
    purchase_price: float | None = None,
    settled: str | None = None,
) -> dict[str, object]:
    """Write actuals for one listing and return the predicted-vs-actual row."""
    df = outcome_tracking.update_scored_listings()
    mask = df["url"].astype(str).str.strip() == url.strip()
    if not mask.any():
        raise SystemExit(
            f"[log-outcome] url not found in {outcome_tracking.SCORING_PATH}.\n"
            "Check the exact listing URL (it must match the scraped url column)."
        )

    df.loc[mask, "actual_sale_price"] = float(sale_price)
    df.loc[mask, "actual_fees_total"] = float(fees)
    df.loc[mask, "reconditioning_cost"] = float(recond)
    df.loc[mask, "settled_date"] = settled or date.today().isoformat()
    if purchase_price is not None:
        df.loc[mask, "purchase_price"] = float(purchase_price)

    write_dataframe_csv_atomic(df, outcome_tracking.SCORING_PATH, index=False)

    # Recompute derived actual_profit / hit columns and the metric files.
    outcome_tracking.compute_outcome_metrics()

    row = pd.read_csv(outcome_tracking.SCORING_PATH)
    row = row[row["url"].astype(str).str.strip() == url.strip()].iloc[0]
    return row.to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="exact listing url")
    parser.add_argument("--sale-price", required=True, type=float, help="what the car resold for")
    parser.add_argument("--fees", type=float, default=0.0, help="total buy+sell fees actually paid")
    parser.add_argument("--recond", type=float, default=0.0, help="actual repair/reconditioning spend")
    parser.add_argument(
        "--purchase-price",
        type=float,
        default=None,
        help="override the hammer price if the tracked value is missing/wrong",
    )
    parser.add_argument("--date", default=None, help="settled date YYYY-MM-DD (default today)")
    args = parser.parse_args()

    row = log_outcome(
        args.url,
        args.sale_price,
        fees=args.fees,
        recond=args.recond,
        purchase_price=args.purchase_price,
        settled=args.date,
    )

    print(f"[log-outcome] recorded outcome for {args.url}")
    print(f"  purchase price:        {_fmt(row.get('purchase_price'))}")
    print(f"  actual sale price:     {_fmt(row.get('actual_sale_price'))}")
    print(f"  actual profit:         {_fmt(row.get('actual_profit'))}")
    print(f"  predicted resale:      {_fmt(row.get('predicted_resale_price'))}")
    print(f"  predicted profit:      {_fmt(row.get('predicted_profit'))}")
    print(f"  recommended max bid:   {_fmt(row.get('recommended_max_bid'))}")
    hit = row.get("hit")
    print(f"  profit-direction hit:  {hit if hit is not None and not pd.isna(hit) else 'n/a (no prediction stored)'}")
    print(f"[log-outcome] metrics refreshed under {outcome_tracking.SCORING_PATH.parent}")


if __name__ == "__main__":
    main()
