"""Show every repair canonical against every vehicle class, and what is still unpriced.

Why
---
`repair_pricing_schedule.csv` carries 28 rows across two classes (`generic` and
`small_hatch`) against a universe of ~164 canonicals and 5 real vehicle classes.
Gaps were being discovered one blocked car at a time: a scratch on an SUV had no
cost band, got flagged `pricing_class_uncertain`, and refused a decision on cars
that were cheap and profitable.

This makes the whole grid visible at once, ranked by how often each cell actually
occurs in real listings, so pricing effort goes where it changes decisions.

Cell status
-----------
    priced            an exact (canonical, vehicle_class) row exists in the schedule
    generic           no class row, but a `generic` row covers it
    MISSING           neither - the cost falls back to a guess and is flagged uncertain
    NO_VEHICLE_CLASS  the listing's body type did not resolve to a class at all

Only canonicals whose review decision implies a real cost are listed. Items decided
`no_cost` (boilerplate) or `hard_avoid` (flat bucket) need no per-class price.

Usage
-----
    python -m scripts.build_repair_pricing_matrix
    python -m scripts.build_repair_pricing_matrix --limit 8000 --min-occurrences 5
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.repair_pricing import (
    REPAIR_PRICING_SCHEDULE_PATH,
    assess_repairs,
    infer_vehicle_class,
)

DEFAULT_SOLD = ROOT_DIR / "CSV_data" / "scrapers" / "sold_cars.csv"
DEFAULT_DECISIONS = ROOT_DIR / "CSV_data" / "reports" / "repair_review_decisions.csv"
DEFAULT_OUTPUT = ROOT_DIR / "CSV_data" / "model_audit" / "repair_pricing_matrix.csv"

# Classes infer_vehicle_class can return.
VEHICLE_CLASSES = ("small_hatch", "small_sedan", "medium_suv", "ute", "van")

# Cost models that need a per-class price. no_cost is boilerplate; hard_avoid uses a
# flat bucket and never consults the schedule.
PRICED_COST_MODELS = {"cosmetic_panel", "fixed_replacement", "glass"}

UNCLASSIFIED = "(no vehicle class)"


def schedule_coverage(path: Path) -> tuple[set, set, dict]:
    """Return (exact class pairs, canonicals with a generic row, priced values)."""
    if not path.exists():
        return set(), set(), {}
    frame = pd.read_csv(path, low_memory=False)
    exact: set = set()
    generic: set = set()
    values: dict = {}
    for _, row in frame.iterrows():
        canonical = str(row.get("canonical_defect") or "").strip()
        klass = str(row.get("vehicle_class") or "").strip().lower()
        if not canonical:
            continue
        values[(canonical, klass)] = row.get("default_estimate")
        if klass == "generic":
            generic.add(canonical)
        elif klass:
            exact.add((canonical, klass))
    return exact, generic, values


def canonicals_needing_price(path: Path) -> dict:
    """canonical -> cost_model, for decisions that imply a real per-class cost."""
    if not path.exists():
        return {}
    frame = pd.read_csv(path, low_memory=False)
    out: dict = {}
    for _, row in frame.iterrows():
        canonical = str(row.get("canonical_defect") or "").strip()
        model = str(row.get("cost_model") or "").strip().lower()
        if canonical and model in PRICED_COST_MODELS:
            out[canonical] = model
    return out


def observed_cells(sold: pd.DataFrame, limit: int) -> Counter:
    """Count (canonical, vehicle_class) as they actually occur in listings."""
    counts: Counter = Counter()
    rows = sold.head(limit) if limit else sold
    for _, row in rows.iterrows():
        condition = str(row.get("general_condition") or "").strip()
        if not condition or condition.lower() == "nan":
            continue
        klass = infer_vehicle_class(row.get("body_type"))
        try:
            assessment = assess_repairs(condition, vehicle_class=klass)
        except Exception:
            continue
        seen: set = set()
        for fragment in getattr(assessment, "fragments", None) or []:
            for canonical in getattr(fragment, "canonical_defects", None) or []:
                canonical = str(canonical).strip()
                if canonical:
                    seen.add(canonical)
        for canonical in seen:
            counts[(canonical, klass or UNCLASSIFIED)] += 1
    return counts


def cell_status(canonical: str, klass: str, exact: set, generic: set) -> str:
    if klass == UNCLASSIFIED:
        return "NO_VEHICLE_CLASS"
    if (canonical, klass) in exact:
        return "priced"
    if canonical in generic:
        return "generic"
    return "MISSING"


def _money(value) -> str:
    text = str(value).strip()
    if text in ("", "nan", "None"):
        return "-"
    try:
        return "$" + format(float(text), ",.0f")
    except (TypeError, ValueError):
        return "-"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Repair pricing coverage matrix.")
    p.add_argument("--sold", type=Path, default=DEFAULT_SOLD)
    p.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    p.add_argument("--schedule", type=Path, default=Path(REPAIR_PRICING_SCHEDULE_PATH))
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--limit", type=int, default=6000,
                   help="Listings to sample for occurrence counts (0 = all).")
    p.add_argument("--min-occurrences", type=int, default=1,
                   help="Hide cells seen fewer times than this.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    exact, generic, values = schedule_coverage(args.schedule)
    needs = canonicals_needing_price(args.decisions)
    print("schedule      : {} class-specific rows, {} generic".format(len(exact), len(generic)))
    print("needs pricing : {} canonicals (cosmetic_panel / fixed_replacement / glass)".format(len(needs)))

    sold = pd.read_csv(args.sold, low_memory=False)
    sampled = min(args.limit, len(sold)) if args.limit else len(sold)
    print("sampling      : {:,} listings".format(sampled))
    counts = observed_cells(sold, args.limit)
    print("observed      : {:,} distinct (canonical, class) cells".format(len(counts)))

    # Full cross product, not just observed combinations. A canonical seen only on a
    # small_hatch today still needs a price for every class, or the first ute that
    # shows it will fall through to a guess and block the decision.
    records = []
    for canonical, model in sorted(needs.items()):
        for klass in VEHICLE_CLASSES:
            records.append({
                "canonical_defect": canonical,
                "vehicle_class": klass,
                "cost_model": model,
                "status": cell_status(canonical, klass, exact, generic),
                "occurrences": counts.get((canonical, klass), 0),
                "schedule_value": values.get((canonical, klass))
                or values.get((canonical, "generic"))
                or "",
                "small_hatch_reference": values.get((canonical, "small_hatch")) or "",
            })

    unclassified_hits = sum(
        n for (canonical, klass), n in counts.items()
        if klass == UNCLASSIFIED and canonical in needs
    )

    if not records:
        print("\nNothing to report - no priced-model canonicals observed.")
        return 0

    matrix = pd.DataFrame(records).sort_values(
        ["occurrences", "canonical_defect", "vehicle_class"], ascending=[False, True, True]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(matrix, args.output, index=False)

    total_cells = len(matrix)
    print("\n=== full grid: {} canonicals x {} classes = {:,} cells ===".format(
        len(needs), len(VEHICLE_CLASSES), total_cells))
    for status, grp in matrix.groupby("status"):
        print("  {:<10} {:4d} cells ({:4.1f}%)   {:7,} listing-hits".format(
            status, len(grp), len(grp) / total_cells * 100, int(grp.occurrences.sum())))

    missing = matrix[matrix.status == "MISSING"]
    seen = missing[missing.occurrences > 0]
    unseen = missing[missing.occurrences == 0]
    print("\n  of {:,} unpriced cells: {:,} already occur in listings, "
          "{:,} not yet seen".format(len(missing), len(seen), len(unseen)))

    if not seen.empty:
        print("\n=== PRICE THESE FIRST - unpriced and already occurring ===")
        print("  {:>7}  {:<30} {:<14} {:>15}".format(
            "hits", "canonical", "class", "small_hatch ref"))
        for _, r in seen.head(25).iterrows():
            print("  {:>7,}  {:<30} {:<14} {:>15}".format(
                int(r.occurrences), str(r.canonical_defect)[:30],
                str(r.vehicle_class), _money(r.small_hatch_reference)))

    if unclassified_hits:
        print("\n  {:,} listing-hits carry NO vehicle class at all (body type did not "
              "resolve).\n  Fix infer_vehicle_class first - those hits will land in these "
              "same cells.".format(unclassified_hits))

    print("\nwritten: {} ({:,} rows)".format(args.output, len(matrix)))
    print("Fill schedule_value per row, then load into repair_pricing_schedule.csv.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
