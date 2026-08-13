"""Rank the UNCLASSIFIED *sold* Autotrader records into a curve-building worklist.

The point: ~92% of the sold evidence can't be used for validation because those
cars don't match a curve. This turns that gap into a prioritised to-do list, so
every curve you build unlocks the most real sold records possible.

It splits the work by *why* a row failed to classify, because the fixes differ:

  TIER 1 - QUICK WINS (no new price research; model already has a curve)
    [OUT_OF_SCOPE_YEAR]  -> extend an existing curve's anchor-year range
    [DISALLOWED_VARIANT] -> allow a variant that's being deliberately excluded
    [AMBIG_BADGE/FUEL/TRANS] -> tighten the matcher so it can disambiguate

  TIER 2 - NEW LANES (build a new curve; model not covered at all)
    [OUT_OF_SCOPE] on a make/model with no existing curve

Outputs to CSV_data/model_audit/:
  curve_worklist_tier1_quick_wins.csv
  curve_worklist_tier2_new_lanes.csv

Each row shows how many SOLD records it would unlock, the year span, and the
median sold price so you can judge whether the lane is worth the effort.

Usage:  python scripts/curve_coverage_worklist.py [--min-sold 5]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.curves import load_curves

ROOT = Path(__file__).resolve().parent.parent
TAGGED = ROOT / "autotrader_isolated" / "output" / "first_page_results_tagged.csv"
OUT_DIR = ROOT / "CSV_data" / "model_audit"

QUICK_WIN_REASONS = {
    "[OUT_OF_SCOPE_YEAR]": "extend curve year range",
    "[DISALLOWED_VARIANT]": "allow excluded variant",
    "[AMBIG_BADGE]": "fix badge matcher",
    "[AMBIG_FUEL]": "fix fuel matcher",
    "[AMBIG_TRANS]": "fix transmission matcher",
}


def _money(v: object) -> float:
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return np.nan


def _covered_models(curves: pd.DataFrame) -> set[tuple[str, str]]:
    models: set[tuple[str, str]] = set()
    for tag in curves["canonical_tag"].astype(str):
        parts = tag.split("_")
        if len(parts) >= 2:
            models.add((parts[0], parts[1]))
    return models


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-sold", type=int, default=5, help="Min sold records to list a lane.")
    args = ap.parse_args()

    curves = load_curves()
    covered = _covered_models(curves)

    d = pd.read_csv(TAGGED, low_memory=False)
    sold = d[d["status"].astype(str).str.lower() == "sold"].copy()
    u = sold[sold["canonical_tag"].astype(str).str.upper() == "UNCLASSIFIED"].copy()

    u["reason"] = u["canonical_reason"].astype(str)
    u["mk"] = u["make"].astype(str).str.strip().str.title()
    u["md"] = u["model"].astype(str).str.strip().str.title()
    u["vr"] = u["variant"].astype(str).str.strip()
    u["body"] = u["body_type"].astype(str).str.strip().str.title()
    u["trans"] = u["transmission"].astype(str).str.strip().str.title()
    u["fuel"] = u["fuel_type"].astype(str).str.strip().str.title()
    u["yr"] = pd.to_numeric(u["year"], errors="coerce")
    u["sold_price"] = u["price"].apply(_money)
    u["has_curve_model"] = [
        (mk.lower(), md.lower()) in covered for mk, md in zip(u["mk"], u["md"])
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- TIER 1: quick wins ----------
    quick = u[u["reason"].isin(QUICK_WIN_REASONS)].copy()
    quick["fix"] = quick["reason"].map(QUICK_WIN_REASONS)
    t1 = (
        quick.groupby(["mk", "md", "vr", "reason", "fix"])
        .agg(
            sold_unlocked=("sold_price", "size"),
            year_min=("yr", "min"),
            year_max=("yr", "max"),
            median_sold=("sold_price", "median"),
        )
        .reset_index()
    )
    t1 = t1[t1["sold_unlocked"] >= args.min_sold].sort_values("sold_unlocked", ascending=False)
    t1["median_sold"] = t1["median_sold"].round(0)
    t1_out = OUT_DIR / "curve_worklist_tier1_quick_wins.csv"
    t1.to_csv(t1_out, index=False)

    # ---------- TIER 2: new lanes ----------
    newlanes = u[(u["reason"] == "[OUT_OF_SCOPE]") & (~u["has_curve_model"])].copy()
    t2 = (
        newlanes.groupby(["mk", "md", "body", "trans", "fuel"])
        .agg(
            sold_unlocked=("sold_price", "size"),
            year_min=("yr", "min"),
            year_max=("yr", "max"),
            median_sold=("sold_price", "median"),
        )
        .reset_index()
    )
    t2 = t2[t2["sold_unlocked"] >= args.min_sold].sort_values("sold_unlocked", ascending=False)
    t2["median_sold"] = t2["median_sold"].round(0)
    t2_out = OUT_DIR / "curve_worklist_tier2_new_lanes.csv"
    t2.to_csv(t2_out, index=False)

    # ---------- summary ----------
    print("=" * 72)
    print("CURVE-BUILDING WORKLIST  (from UNCLASSIFIED *sold* Autotrader records)")
    print("=" * 72)
    print(f"Sold + UNCLASSIFIED records analysed: {len(u):,}")
    print(f"  Tier 1 quick-win records (model already curved): {int(quick.shape[0]):,}")
    print(f"  Tier 2 new-lane records (no curve for model):    {int(newlanes.shape[0]):,}")
    print()
    print(f"TIER 1 - QUICK WINS  (>= {args.min_sold} sold; extend/allow/matcher, no new pricing)")
    print(f"  {len(t1)} lanes unlock {int(t1['sold_unlocked'].sum()):,} sold records")
    cols1 = ["mk", "md", "vr", "fix", "sold_unlocked", "year_min", "year_max", "median_sold"]
    print(t1.head(15)[cols1].to_string(index=False))
    print()
    print(f"TIER 2 - NEW LANES  (>= {args.min_sold} sold; build a new curve)")
    print(f"  {len(t2)} lanes unlock {int(t2['sold_unlocked'].sum()):,} sold records")
    cols2 = ["mk", "md", "body", "trans", "fuel", "sold_unlocked", "year_min", "year_max", "median_sold"]
    print(t2.head(20)[cols2].to_string(index=False))
    print()
    print(f"Wrote: {t1_out}")
    print(f"Wrote: {t2_out}")


if __name__ == "__main__":
    main()
