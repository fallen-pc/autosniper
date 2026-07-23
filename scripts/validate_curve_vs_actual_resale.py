"""Validate curve resale estimates against Autotrader end-state outcomes.

This is a NON-CIRCULAR check. The curves were built from Carsales *asking*
(active-listing) prices. This script compares each curve's mid estimate against
the price Autotrader listings actually *ended at when they sold*, plus how long
they took to sell. That end-state information is not part of the asking snapshots
the curve was built from, so it is independent evidence of the asking -> achieved
gap the bidding cap depends on.

What it produces (written to CSV_data/model_audit/):
  1. curve_vs_actual_resale_by_tag.csv  -- per curve tag:
       curve mid, median final advertised price, ratio, median days-to-sell, sample size
  2. curve_vs_actual_resale_detail.csv  -- per sold car:
       curve mid for its year+km, actual sold price, gap, days on market, drop %

It also prints an overall summary, including the implied resale haircut vs the
8% (BASE_DOWNSIDE_PCT) the valuation currently assumes.

Caveats (read before trusting a number):
  * "sold" is Autotrader's disappearance signal; some rows may be withdrawals,
    not genuine sales. Spot-check the scraper's sold/relisted logic.
  * "actual sold price" here is the LAST advertised price before the listing
    left the site -- still an asking price, so it is a CEILING on the true
    transacted price (buyers usually negotiate a little more off).

Usage (from any directory):
    python scripts/validate_curve_vs_actual_resale.py
    python scripts/validate_curve_vs_actual_resale.py --min-comps 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.curves import interpolate_base_by_year, load_curves, resolve_curve_canonical_tag

ROOT = Path(__file__).resolve().parent.parent
AT_DIR = ROOT / "autotrader_isolated" / "output"
STATE_PATH = AT_DIR / "listing_state.csv"
HISTORY_PATH = AT_DIR / "listing_history.csv"
TAGGED_PATH = AT_DIR / "first_page_results_tagged.csv"
RECENT_TAGGED_PATH = AT_DIR / "autotrader_recent_market_tagged.csv"
CURVES_PATH = ROOT / "CSV_data" / "restricted" / "curves.csv"
OUT_DIR = ROOT / "CSV_data" / "model_audit"
BASE_DOWNSIDE_PCT = 0.08  # mirror scripts.ai_listing_valuation
DEFAULT_MAX_DISAPPEARANCE_GAP_DAYS = 5.0


def _money(value: object) -> float:
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return np.nan


def _int(value: object) -> "int | None":
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def load_sold_listings() -> pd.DataFrame:
    """One row per SOLD Autotrader listing with start price, end price, days-on-market, tag."""
    state = pd.read_csv(STATE_PATH, low_memory=False)
    sold = state[state["status"].astype(str).str.lower() == "sold"].copy()
    sold["end_price"] = sold["last_price"].apply(_money)
    sold["first_seen_dt"] = pd.to_datetime(sold["first_seen"], errors="coerce")
    sold["last_seen_dt"] = pd.to_datetime(sold["last_seen"], errors="coerce")
    sold["sold_date_dt"] = pd.to_datetime(sold["sold_date"], errors="coerce")
    sold["days_on_market"] = (sold["last_seen_dt"] - sold["first_seen_dt"]).dt.days
    sold["disappearance_gap_days"] = (
        sold["sold_date_dt"] - sold["last_seen_dt"]
    ).dt.total_seconds() / 86_400

    # First advertised price, from the history event log.
    hist = pd.read_csv(HISTORY_PATH, low_memory=False)
    hist["p"] = hist["price"].apply(_money)
    hist["d"] = pd.to_datetime(hist["event_date"], errors="coerce")
    first_price = (
        hist.sort_values("d").groupby("url").agg(start_price=("p", "first")).reset_index()
    )
    sold = sold.merge(first_price, on="url", how="left")

    # Canonical tag, from the tagged scrape output.
    tagged_frames = [
        pd.read_csv(path, low_memory=False)
        for path in (RECENT_TAGGED_PATH, TAGGED_PATH)
        if path.exists()
    ]
    tagged = pd.concat(tagged_frames, ignore_index=True) if tagged_frames else pd.DataFrame()
    tag_cols = ["url", "canonical_tag"]
    tagged = tagged[[c for c in tag_cols if c in tagged.columns]].drop_duplicates("url")
    sold = sold.merge(tagged, on="url", how="left")

    sold["odo"] = pd.to_numeric(sold["odometer"], errors="coerce")
    sold["year_int"] = sold["year"].apply(_int)
    return sold


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-comps", type=int, default=5, help="Min sold cars per tag to report it.")
    parser.add_argument(
        "--max-disappearance-gap-days",
        type=float,
        default=DEFAULT_MAX_DISAPPEARANCE_GAP_DAYS,
        help=(
            "Exclude sold-status rows where sold_date is more than this many days "
            "after last_seen (default: 5). These are incomplete outcomes after a "
            "tracking pause, not clean daily disappearance signals."
        ),
    )
    args = parser.parse_args()

    curves = load_curves(CURVES_PATH)
    sold = load_sold_listings()
    delayed_outcomes = sold["disappearance_gap_days"] > args.max_disappearance_gap_days
    delayed_count = int(delayed_outcomes.fillna(False).sum())
    sold = sold[~delayed_outcomes.fillna(True)].copy()

    # Keep only sold cars we can map to a curve and price for a curve mid.
    # Resolve each DISTINCT canonical tag once (per-row apply over ~19k rows is slow).
    unique_tags = sold["canonical_tag"].dropna().astype(str).unique()
    tag_map = {t: resolve_curve_canonical_tag(t, curves_df=curves) for t in unique_tags}
    sold["curve_tag"] = sold["canonical_tag"].astype(str).map(tag_map).fillna("")
    allowed = set(curves["canonical_tag"].astype(str).str.strip())
    sold = sold[sold["curve_tag"].isin(allowed)].copy()

    # Curve mid for each car's own year + km. Memoize on (tag, year, km rounded
    # to 5k) so we call the interpolation once per distinct combo, not once per
    # listing -- turns ~19k slow curve-filter calls into a few thousand.
    _cache: dict[tuple, "float | None"] = {}

    def _curve_mid(tag: str, year: "int | None", km: float) -> "float | None":
        if not tag or year is None or not np.isfinite(km):
            return None
        key = (tag, int(year), int(round(km / 5000.0) * 5000))
        if key not in _cache:
            _cache[key] = interpolate_base_by_year(curves, tag, key[1], key[2])
        return _cache[key]

    sold["curve_mid"] = [
        _curve_mid(t, y, k)
        for t, y, k in zip(sold["curve_tag"], sold["year_int"], sold["odo"])
    ]

    detail = sold.dropna(subset=["curve_mid", "end_price"]).copy()
    detail = detail[(detail["curve_mid"] > 0) & (detail["end_price"] > 0)]
    if detail.empty:
        print("No sold Autotrader listings could be matched to a curve mid. Check tagging/coverage.")
        return

    detail["actual_vs_curve"] = detail["end_price"] / detail["curve_mid"]
    detail["gap_dollars"] = detail["end_price"] - detail["curve_mid"]
    detail["drop_from_start"] = detail["start_price"] - detail["end_price"]
    detail["drop_pct"] = detail["drop_from_start"] / detail["start_price"]

    keep = [
        "url", "curve_tag", "year_int", "odo", "start_price", "end_price",
        "curve_mid", "gap_dollars", "actual_vs_curve", "drop_pct", "days_on_market",
        "disappearance_gap_days",
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    detail_out = OUT_DIR / "curve_vs_actual_resale_detail.csv"
    detail[keep].to_csv(detail_out, index=False)

    by_tag = (
        detail.groupby("curve_tag")
        .agg(
            sold_cars=("end_price", "size"),
            curve_mid_median=("curve_mid", "median"),
            actual_sold_median=("end_price", "median"),
            actual_vs_curve_median=("actual_vs_curve", "median"),
            median_days_to_sell=("days_on_market", "median"),
            pct_dropped_price=("drop_pct", lambda s: float((s > 0).mean())),
        )
        .reset_index()
    )
    by_tag = by_tag[by_tag["sold_cars"] >= args.min_comps].sort_values("actual_vs_curve_median")
    for col in ("curve_mid_median", "actual_sold_median"):
        by_tag[col] = by_tag[col].round(0)
    by_tag["actual_vs_curve_median"] = by_tag["actual_vs_curve_median"].round(3)
    by_tag["pct_dropped_price"] = (by_tag["pct_dropped_price"] * 100).round(0)
    by_tag_out = OUT_DIR / "curve_vs_actual_resale_by_tag.csv"
    by_tag.to_csv(by_tag_out, index=False)

    # ---- Overall summary ----
    overall_ratio = float(detail["actual_vs_curve"].median())
    implied_haircut = (1.0 - overall_ratio) * 100
    print("=" * 70)
    print("CURVE MID vs AUTOTRADER FINAL ADVERTISED PRICE  (non-circular validation)")
    print("=" * 70)
    print(f"Sold cars matched to a curve:        {len(detail):,}")
    print(
        f"Delayed/incomplete outcomes excluded: {delayed_count:,} "
        f"(gap > {args.max_disappearance_gap_days:g} days)"
    )
    print(f"Curve tags with >= {args.min_comps} sold cars:      {len(by_tag)}")
    print()
    print(f"Median final-advertised / curve-mid: {overall_ratio:.3f}")
    print(f"  -> listings ended at ~{overall_ratio*100:.0f}% of curve mid")
    print(f"  -> implied resale haircut:         {implied_haircut:.0f}%")
    print(f"  -> valuation currently assumes:    {BASE_DOWNSIDE_PCT*100:.0f}% (BASE_DOWNSIDE_PCT)")
    verdict = "OPTIMISTIC (caps too high)" if implied_haircut > BASE_DOWNSIDE_PCT * 100 + 2 else \
              "CONSERVATIVE (caps safe)" if implied_haircut < BASE_DOWNSIDE_PCT * 100 - 2 else "about right"
    print(f"  -> curve mid looks {verdict}")
    print()
    print(f"Median days-to-sell:                 {detail['days_on_market'].median():.0f} days")
    print(f"Listings that cut price before sale: {(detail['drop_pct'] > 0).mean()*100:.0f}%")
    print()
    print("MOST OPTIMISTIC curve tags (final advertised price below curve mid):")
    show = by_tag.head(10)[
        ["curve_tag", "sold_cars", "curve_mid_median", "actual_sold_median",
         "actual_vs_curve_median", "median_days_to_sell"]
    ]
    print(show.to_string(index=False))
    print()
    print(f"Wrote: {by_tag_out}")
    print(f"Wrote: {detail_out}")


if __name__ == "__main__":
    main()
