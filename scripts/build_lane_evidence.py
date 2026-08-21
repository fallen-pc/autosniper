"""Summarise verified Autotrader exits for one vehicle lane, to scope a new curve.

EVIDENCE ONLY - NOT A CURVE INPUT
---------------------------------
Project policy is that curve prices are Carsales/Apify-led; Autotrader is
comparison and follow-up evidence only. This tool exists to answer "is this lane
worth building, and what shape is it?" before spending time gathering Carsales
evidence. Do not paste these numbers into curves.csv.

Two further reasons not to treat the output as prices:

* `final_asking_price` is an ASKING price. Cars sell below asking by an amount
  this data does not measure - only the ~3.7% median public price cut is visible.
* Cell counts are small. A km bucket backed by three listings is an anecdote.

What it does
------------
Filters confirmed exits (verified by direct URL poll, not the unreliable legacy
`sold` flag) to one make/model/body, using the canonical tagger's own normalisers
so messy source strings like "Double Cab Pick Up" / "Dual Cab Pick-up" /
"Dual Cab Utility" collapse correctly. Then reports the price-vs-odometer shape
per variant and anchor year, on the standard curve km grid.

Usage
-----
    python -m scripts.build_lane_evidence --make toyota --model hilux --body dualcab_ute
    python -m scripts.build_lane_evidence --make toyota --model kluger --list-bodies
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

AUTOTRADER_OUT = ROOT_DIR / "autotrader_isolated" / "output"
EXIT_STATE = AUTOTRADER_OUT / "listing_exit_state.csv"
LISTING_STATE = AUTOTRADER_OUT / "listing_state.csv"
DEFAULT_OUT_DIR = ROOT_DIR / "CSV_data" / "model_audit" / "lane_evidence"

# The grid curves.csv is built on.
KM_GRID = (30_000, 60_000, 100_000, 150_000, 200_000)
SPEC_COLUMNS = ("year", "make", "model", "variant", "body_type", "odometer",
                "transmission", "fuel_type", "location")


def load_confirmed_exits() -> pd.DataFrame:
    """Confirmed exits joined to their spec. Verified by poll, not the legacy flag."""
    if not EXIT_STATE.exists():
        raise FileNotFoundError(f"no exit state: {EXIT_STATE}")
    state = pd.read_csv(EXIT_STATE, low_memory=False)
    confirmed = state[is_real_tag(state["confirmed_gone_date"])].copy()
    keep = [c for c in ("url", "exit_price", "confirmed_gone_date") if c in confirmed.columns]
    confirmed = confirmed[keep]
    confirmed["url"] = confirmed["url"].astype(str).str.strip()

    listings = pd.read_csv(LISTING_STATE, low_memory=False)
    listings["url"] = listings["url"].astype(str).str.strip()
    cols = ["url", "last_price", *[c for c in SPEC_COLUMNS if c in listings.columns]]
    listings = listings[cols].drop_duplicates(subset=["url"])

    merged = confirmed.merge(listings, on="url", how="left")
    price = pd.to_numeric(merged.get("exit_price"), errors="coerce")
    fallback = pd.to_numeric(merged.get("last_price"), errors="coerce")
    merged["asking_price"] = price.where(price.notna() & (price > 0), fallback)
    merged["odometer_km"] = pd.to_numeric(merged.get("odometer"), errors="coerce")
    merged["year_int"] = pd.to_numeric(merged.get("year"), errors="coerce")
    return merged


def add_normalised_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the canonical tagger's own normalisers so messy strings collapse."""
    from shared.canonical_tagging import _normalize_body, _normalize_make, _normalize_model

    frame = frame.copy()
    frame["make_norm"] = frame["make"].apply(_normalize_make)
    frame["model_norm"] = frame["model"].apply(_normalize_model)
    frame["body_norm"] = frame["body_type"].apply(lambda v: _normalize_body(v, ""))
    return frame


def km_bucket(km: float) -> object:
    """Nearest grid point at or above km, for grouping onto the curve grid."""
    if pd.isna(km):
        return pd.NA
    for point in KM_GRID:
        if km <= point:
            return point
    return KM_GRID[-1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scope a candidate curve lane from verified exits.")
    p.add_argument("--make", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--body", default=None,
                   help="Normalised body (e.g. dualcab_ute). Omit to include all.")
    p.add_argument("--list-bodies", action="store_true",
                   help="Show the normalised body split for this make/model and exit.")
    p.add_argument("--min-price", type=float, default=1000.0)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    data = add_normalised_columns(load_confirmed_exits())
    make = str(args.make).strip().lower()
    model = str(args.model).strip().lower()

    lane = data[(data["make_norm"] == make) & (data["model_norm"] == model)].copy()
    print(f"confirmed exits for {make} {model}: {len(lane):,}")
    if lane.empty:
        print("Nothing to report.")
        return 1

    if args.list_bodies or not args.body:
        print("\nnormalised body split:")
        print(lane["body_norm"].value_counts().to_string())
        if args.list_bodies:
            return 0

    if args.body:
        lane = lane[lane["body_norm"] == str(args.body).strip().lower()]
        print(f"\nbody '{args.body}': {len(lane):,} rows")

    lane = lane[pd.to_numeric(lane["asking_price"], errors="coerce") >= args.min_price]
    lane = lane.dropna(subset=["asking_price"])
    if lane.empty:
        print("No priced rows after filtering.")
        return 1

    price = pd.to_numeric(lane["asking_price"], errors="coerce")
    km = pd.to_numeric(lane["odometer_km"], errors="coerce")
    print(f"\nasking price : median ${price.median():,.0f}  "
          f"p10 ${price.quantile(.1):,.0f}  p90 ${price.quantile(.9):,.0f}")
    print(f"odometer     : median {km.median():,.0f} km  "
          f"p10 {km.quantile(.1):,.0f}  p90 {km.quantile(.9):,.0f}")
    print(f"year         : {lane['year_int'].min():.0f} - {lane['year_int'].max():.0f}")

    print("\n=== variants present (curve lanes are usually per variant) ===")
    variants = lane["variant"].astype(str).str.strip().value_counts()
    for name, n in variants.head(15).items():
        sub = pd.to_numeric(lane.loc[lane["variant"].astype(str).str.strip() == name,
                                     "asking_price"], errors="coerce")
        print(f"  {n:4,}  {name[:42]:<42} median ${sub.median():,.0f}")

    lane["km_bucket"] = km.apply(km_bucket)
    print("\n=== price by odometer bucket (all variants pooled) ===")
    print(f"  {'km':>8}  {'n':>5}  {'p25':>9}  {'median':>9}  {'p75':>9}")
    for point in KM_GRID:
        cell = pd.to_numeric(lane.loc[lane["km_bucket"] == point, "asking_price"],
                             errors="coerce").dropna()
        if cell.empty:
            print(f"  {point:>8,}  {0:>5}          -          -          -")
            continue
        flag = "  <- thin" if len(cell) < 5 else ""
        print(f"  {point:>8,}  {len(cell):>5}  ${cell.quantile(.25):>8,.0f}  "
              f"${cell.median():>8,.0f}  ${cell.quantile(.75):>8,.0f}{flag}")

    print("\n=== year x km cell counts (curve needs an anchor year per row) ===")
    pivot = lane.pivot_table(index="year_int", columns="km_bucket",
                             values="asking_price", aggfunc="count").fillna(0).astype(int)
    print(pivot.to_string())

    args.output_dir.mkdir(parents=True, exist_ok=True)
    slug = f"{make}_{model}" + (f"_{args.body}" if args.body else "")
    out = args.output_dir / f"{slug}_exit_evidence.csv"
    export_cols = ["url", "year", "variant", "body_type", "body_norm", "odometer_km",
                   "km_bucket", "transmission", "fuel_type", "asking_price",
                   "confirmed_gone_date", "location"]
    # Sort before slicing: year_int is a sort key but not an exported column.
    ordered = lane.sort_values([c for c in ("variant", "year_int", "odometer_km")
                                if c in lane.columns])
    write_dataframe_csv_atomic(
        ordered[[c for c in export_cols if c in ordered.columns]],
        out,
        index=False,
    )
    print(f"\nevidence written: {out} ({len(lane):,} rows)")
    print("\nEVIDENCE ONLY. Curve prices must come from Carsales/Apify per project policy,")
    print("and these are ASKING prices, not realised sales.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
