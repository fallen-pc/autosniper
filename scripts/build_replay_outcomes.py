"""Score today's decision policy against observed retail outcomes.

The question this answers
-------------------------
Of the cars the CURRENT system would have said Buy, how many would actually have
been profitable? Nothing in the project could answer that before: no cars have
been bought, so `actual_profit` is empty on all 23,179 rows of
`scored_listings_enriched.csv`, and the 732 rows that do carry a verdict were
scored under a retired vocabulary (Trap / Bronze / Conditional Flip / Strong
Flip) rather than the current Buy / Watch / Avoid / Review policy.

Avoiding the circularity trap
-----------------------------
The obvious construction is worthless. If the decision and the outcome both use
the same resale estimate, the test is nearly tautological: the system says Buy
when close price sits below resale minus costs minus margin, so scoring "was
resale minus close minus costs positive" just re-derives the rule. A broken
resale model would score perfectly.

So the two sides are deliberately fed from independent sources:

    PREDICTION  uses the CURVE resale (interpolate_base_by_year) - exactly what
                the live page had at decision time.
    OUTCOME     uses the OBSERVED retail exit median, built from listings whose
                removal was verified by polling their own URL.

The curve is hand-built from Carsales evidence; the exits are scraped market
observations. They are genuinely independent, so agreement is informative and
disagreement is a real finding.

What the outcome is, and is not
-------------------------------
`retail_estimate` is a median of ASKING prices. Cars sell below asking by an
amount this data does not measure - only the ~3.7% median public price cut is
visible. So this measures SELECTION QUALITY (does the ranking separate winners
from losers), not realised profit. Read the margin, not the decimal.

Usage
-----
    python -m scripts.build_replay_outcomes
    python -m scripts.build_replay_outcomes --min-lane-obs 10 --output out.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from scripts.atomic_csv import write_dataframe_csv_atomic
from scripts.build_retail_exit_ledger import is_real_tag
from shared.comps_engine import parse_currency, parse_numeric
from shared.curves import interpolate_base_by_year, load_curves, resolve_curve_canonical_tag
from shared.data_loader import dataset_path
from shared.missed_opportunities import compute_decision_metrics

DEFAULT_SOLD = dataset_path("sold_cars.csv")
DEFAULT_LEDGER = ROOT_DIR / "CSV_data" / "model_audit" / "retail_exit_ledger.csv"
DEFAULT_OUTPUT = ROOT_DIR / "CSV_data" / "model_audit" / "replay_outcomes.csv"

# Retail match tolerances, mirroring generate_retail_median_outcomes.py.
YEAR_TOLERANCE = 2
KM_TOLERANCE_PCT = 0.30
MIN_RETAIL_MATCHES = 5
DEFAULT_MIN_PROFIT = 1500.0

OUTPUT_COLUMNS = [
    "url",
    "curve_tag",
    "year",
    "make",
    "model",
    "variant",
    "odometer_km",
    "sold_price",
    "curve_resale",
    "retail_estimate",
    "retail_match_count",
    "action_label",
    "computed_verdict",
    "bid_status",
    "hard_max_safety",
    "max_bid",
    "repair_cost",
    "total_costs",
    "simulated_profit",
    "is_profitable_actual",
    "y_pred_buy",
]


def retail_estimate_for(
    lane_rows: pd.DataFrame, year: float | None, km: float | None
) -> tuple[float | None, int]:
    """Median asking price of verified exits matching this vehicle's year and km.

    A flat per-lane median would compare a 30k car against a 250k one, so matches
    are restricted to +/-2 years and +/-30% odometer before taking the median.
    """
    if lane_rows.empty:
        return None, 0
    candidates = lane_rows
    if year is not None and not pd.isna(year):
        years = pd.to_numeric(candidates["year"], errors="coerce")
        candidates = candidates[(years - year).abs() <= YEAR_TOLERANCE]
    if km is not None and not pd.isna(km) and km > 0:
        kms = pd.to_numeric(candidates["odometer"], errors="coerce")
        candidates = candidates[(kms - km).abs() <= km * KM_TOLERANCE_PCT]
    prices = pd.to_numeric(candidates.get("final_asking_price"), errors="coerce").dropna()
    prices = prices[prices > 0]
    if len(prices) < MIN_RETAIL_MATCHES:
        return None, len(prices)
    return float(prices.median()), len(prices)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Replay the current policy against observed exits.")
    p.add_argument("--sold", type=Path, default=DEFAULT_SOLD)
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--min-lane-obs", type=int, default=10,
                   help="Only replay lanes with at least this many verified exits (default 10).")
    p.add_argument("--min-profit", type=float, default=DEFAULT_MIN_PROFIT,
                   help="Profit threshold that counts as a good outcome (default 1500).")
    p.add_argument("--limit", type=int, default=0, help="Cap rows replayed, for a quick check.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.ledger.exists():
        print(f"ERROR: no exit ledger at {args.ledger}. Run build_retail_exit_ledger first.")
        return 1
    ledger = pd.read_csv(args.ledger, low_memory=False)
    ledger = ledger[is_real_tag(ledger["curve_tag"])]
    lane_counts = ledger["curve_tag"].value_counts()
    deep = set(lane_counts[lane_counts >= args.min_lane_obs].index)
    ledger = ledger[ledger["curve_tag"].isin(deep)]
    print(f"exit ledger : {len(ledger):,} observations across {len(deep):,} lanes "
          f"(>= {args.min_lane_obs} obs)")
    if ledger.empty:
        print("No lane meets the observation threshold.")
        return 1
    # The ledger stores odometer under its own name; normalise for matching.
    if "odometer" not in ledger.columns:
        ledger["odometer"] = pd.NA
    lanes = {tag: rows for tag, rows in ledger.groupby("curve_tag")}

    sold = pd.read_csv(args.sold, low_memory=False)
    print(f"sold rows   : {len(sold):,}")
    curves_df = load_curves()

    if "canonical_tag" not in sold.columns:
        print("ERROR: sold source has no canonical_tag.")
        return 1
    sold["curve_tag"] = sold["canonical_tag"].astype(str).str.strip().apply(
        lambda t: resolve_curve_canonical_tag(t, curves_df=curves_df) if t else ""
    )
    sold = sold[sold["curve_tag"].isin(deep)].copy()
    print(f"  in replayable lanes: {len(sold):,}")
    if sold.empty:
        print("No sold rows fall in the covered lanes.")
        return 1

    sold["sold_price"] = sold["price"].apply(parse_currency)
    sold["odometer_km"] = (
        sold["odometer_reading"].apply(parse_numeric)
        if "odometer_reading" in sold.columns
        else pd.NA
    )
    sold["year_num"] = pd.to_numeric(sold.get("year"), errors="coerce")
    sold = sold[pd.to_numeric(sold["sold_price"], errors="coerce").fillna(0) > 0]
    if args.limit:
        sold = sold.head(args.limit)
    print(f"  with a sold price  : {len(sold):,}")

    records: list[dict[str, object]] = []
    skipped_no_curve = 0
    skipped_no_retail = 0

    for _, row in sold.iterrows():
        tag = row["curve_tag"]
        year = row["year_num"]
        km = row["odometer_km"]

        # PREDICTION side: the curve resale the live page would have used.
        curve_resale = interpolate_base_by_year(
            curves_df, str(row.get("canonical_tag") or ""), None if pd.isna(year) else int(year), km
        )
        if not curve_resale or curve_resale <= 0:
            skipped_no_curve += 1
            continue

        # OUTCOME side: independent, from verified retail exits.
        retail, matches = retail_estimate_for(lanes.get(tag, pd.DataFrame()), year, km)
        if retail is None:
            skipped_no_retail += 1
            continue

        # compute_decision_metrics reads the close price from `price_numeric`, not
        # `price`. Without it sold_price is None, the whole cost/verdict block is
        # skipped, and every row falls back to Review with zero costs.
        listing_data = dict(row)
        listing_data["price_numeric"] = float(row["sold_price"])

        metrics = compute_decision_metrics(listing_data, curve_resale, include_repairs=True)
        action = str(metrics.get("action_label") or "").strip()
        total_costs = float(metrics.get("total_costs") or 0.0)
        sold_price = float(row["sold_price"])
        simulated_profit = retail - sold_price - total_costs

        records.append(
            {
                "url": row.get("url"),
                "curve_tag": tag,
                "year": year,
                "make": row.get("make"),
                "model": row.get("model"),
                "variant": row.get("variant"),
                "odometer_km": km,
                "sold_price": sold_price,
                "curve_resale": curve_resale,
                "retail_estimate": retail,
                "retail_match_count": matches,
                "action_label": action,
                "computed_verdict": metrics.get("computed_verdict"),
                "bid_status": metrics.get("bid_status"),
                "hard_max_safety": metrics.get("hard_max_safety"),
                "max_bid": metrics.get("max_bid"),
                "repair_cost": metrics.get("repair_cost"),
                "total_costs": total_costs,
                "simulated_profit": simulated_profit,
                "is_profitable_actual": bool(simulated_profit >= args.min_profit),
                "y_pred_buy": action == "Buy",
            }
        )

    print(f"\nskipped, no curve price : {skipped_no_curve:,}")
    print(f"skipped, thin retail    : {skipped_no_retail:,} "
          f"(needs >= {MIN_RETAIL_MATCHES} matches within +/-{YEAR_TOLERANCE}yr, "
          f"+/-{int(KM_TOLERANCE_PCT*100)}% km)")

    out = pd.DataFrame(records).reindex(columns=OUTPUT_COLUMNS)
    if out.empty:
        print("\nNothing replayable. Widen --min-lane-obs or extend curve coverage.")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(out, args.output, index=False)
    print(f"\nreplayed: {len(out):,} rows -> {args.output}")

    print("\n=== action labels the CURRENT policy assigns ===")
    print(out["action_label"].value_counts().to_string())

    y_pred = out["y_pred_buy"].astype(bool)
    y_true = out["is_profitable_actual"].astype(bool)
    tp = int((y_pred & y_true).sum())
    fp = int((y_pred & ~y_true).sum())
    fn = int((~y_pred & y_true).sum())
    tn = int((~y_pred & ~y_true).sum())

    print(f"\n=== selection quality (profit threshold ${args.min_profit:,.0f}) ===")
    print(f"  would have bought      : {tp + fp:,}")
    print(f"  actually profitable    : {tp + fn:,}")
    print(f"  true positive          : {tp:,}")
    print(f"  false positive         : {fp:,}   (bought, not profitable)")
    print(f"  false negative         : {fn:,}   (passed, would have profited)")
    print(f"  true negative          : {tn:,}")
    if tp + fp:
        print(f"  precision              : {tp / (tp + fp) * 100:.1f}%")
    else:
        print("  precision              : n/a - the policy said Buy to nothing")
    if tp + fn:
        print(f"  recall                 : {tp / (tp + fn) * 100:.1f}%")

    print("\nretail_estimate is a median of ASKING prices. This measures selection")
    print("quality, not realised profit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
