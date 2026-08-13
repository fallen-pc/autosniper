"""Add the final 2011 model year to the governed BMW 320i Executive E90 curve."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.atomic_csv import write_dataframe_csv_atomic


ROOT = Path(__file__).resolve().parent.parent
CURVES = ROOT / "CSV_data" / "restricted" / "curves.csv"
OVERRIDES = ROOT / "config" / "curve_anchor_overrides_v2.csv"
TAG = "bmw_320i-executive_e90_sedan_auto_petrol"


def main() -> int:
    curves = pd.read_csv(CURVES)
    lane = curves[curves["canonical_tag"].eq(TAG)].copy()
    if lane.empty:
        raise RuntimeError(f"Missing governed lane: {TAG}")
    if 2011 in set(pd.to_numeric(lane["anchor_year"], errors="coerce")):
        print("BMW 320i Executive E90 2011 anchor already present.")
        return 0

    by_year = {
        int(year): frame.set_index("km_bucket")
        for year, frame in lane.groupby("anchor_year")
    }
    if 2009 not in by_year or 2010 not in by_year:
        raise RuntimeError("Expected 2009 and 2010 anchors for conservative extrapolation")
    prior = by_year[2009]
    latest = by_year[2010]
    rows: list[dict[str, object]] = []
    for km_bucket in sorted(set(prior.index) & set(latest.index)):
        row: dict[str, object] = {
            "canonical_tag": TAG,
            "anchor_year": 2011,
            "km_bucket": int(km_bucket),
        }
        for column in ("price_low", "price_mid", "price_high"):
            delta = float(latest.loc[km_bucket, column]) - float(
                prior.loc[km_bucket, column]
            )
            value = float(latest.loc[km_bucket, column]) + delta
            row[column] = int(round(value / 100.0) * 100)
        rows.append(row)

    updated = pd.concat(
        [curves, pd.DataFrame(rows, columns=curves.columns)], ignore_index=True
    ).sort_values(["canonical_tag", "anchor_year", "km_bucket"])
    write_dataframe_csv_atomic(updated, CURVES, index=False)

    overrides = pd.read_csv(OVERRIDES, low_memory=False)
    mask = overrides["base_curve_tag"].eq(TAG)
    overrides.loc[mask, "anchor_years"] = "2006|2009|2010|2011"
    overrides.loc[mask, "notes"] = (
        "Existing 22-row private Carsales E90 curve extended to the final 2011 model "
        "year by continuing the observed 2009-to-2010 premium once; six unique live "
        "Grays 2011 Executive E90 vehicles justify coverage. 2012 and F30 stay excluded."
    )
    write_dataframe_csv_atomic(overrides, OVERRIDES, index=False)
    print(f"Added {len(rows)} governed 2011 BMW 320i Executive E90 curve cells.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
