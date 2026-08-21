"""Write genuinely class-specific web-research findings into the pricing schedule.

What this is NOT
-----------------
Not a multiplier. repair_pricing_schedule.py's own validator carries the line
"evidence_source is required; do not invent class multipliers" - scaling a
small_hatch price by a guessed size ratio was considered and explicitly rejected
for that reason. Every row below is independently sourced for that specific
vehicle class, not derived from another class's number.

What this IS
-------------
Four rows where a second round of class-targeted web research (not general
"repair cost Australia" queries, but ute/SUV/sedan-specific ones) turned up a
genuinely different repair scope or cost band for that class - not the same
national figure restated. Everything else searched for came back with one flat
range regardless of vehicle class (or explicitly "contact a local repairer for
a quote"), so it is left MISSING rather than filled with a non-finding.

  corrosion_damage / ute         chassis & frame rust repair, a materially
                                  different (and pricier) job than wheel-arch
                                  rust on a monocoque car
  corrosion_damage / medium_suv  wheel-arch panel replacement, sedan and
                                  compact-SUV figure given together in the
                                  source
  corrosion_damage / small_sedan same source, same figure as medium_suv above
  seat_damage / ute              bench-seat reupholster, priced as its own job
                                  type distinct from bucket-seat pricing - utes
                                  commonly run a bench seat

Marked confidence="low" and pricing_method="internal_default" (not
"repair_quote") throughout - these are published price-guide figures, not a
firm quote for a specific vehicle. The 20 quote requests already drafted
(repair_quote_requests.csv, RQ-0059 to RQ-0078) are what will produce real,
high-confidence numbers; when a reply comes in, replace the matching row here
via pricing_row_from_quote() rather than leaving both on file.

Usage
-----
    python -m scripts.apply_researched_repair_prices
    python -m scripts.apply_researched_repair_prices --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from shared.repair_pricing_schedule import (
    PRICING_COLUMNS,
    load_pricing_schedule,
    save_pricing_schedule,
    validate_pricing_schedule,
)

TODAY = date(2026, 8, 19).isoformat()

RESEARCHED_ROWS = [
    {
        "canonical_defect": "corrosion_damage",
        "category": "cosmetic",
        "vehicle_class": "ute",
        "pricing_method": "internal_default",
        "low_estimate": 2000,
        "default_estimate": 2800,
        "high_estimate": 4000,
        "confidence": "low",
        "evidence_source": "Dinggo - car rust repair cost guide (AU)",
        "evidence_date": TODAY,
        "supplier": "",
        "vehicle_specific": "no",
        "labour_required": "yes",
        "notes": (
            "Frame/chassis rust repair, $2,000-4,000 (AU). Distinct job from wheel-arch "
            "rust on a monocoque car - utes carry chassis/tray rust exposure the other "
            "classes don't. Source: "
            "https://www.dinggo.com.au/blog/what-is-the-estimated-cost-of-car-rust-repair "
            "Interim, pending real supplier quote RQ-0076."
        ),
    },
    {
        "canonical_defect": "corrosion_damage",
        "category": "cosmetic",
        "vehicle_class": "medium_suv",
        "pricing_method": "internal_default",
        "low_estimate": 350,
        "default_estimate": 475,
        "high_estimate": 600,
        "confidence": "low",
        "evidence_source": "PartCatalog - wheel arch repair panel replacement cost guide",
        "evidence_date": TODAY,
        "supplier": "",
        "vehicle_specific": "no",
        "labour_required": "yes",
        "notes": (
            "Wheel-arch panel replacement, $350-600 (AU) - source gives this figure "
            "specifically for \"mid-size sedans and compact SUVs\". Source: "
            "https://www.partcatalog.com/blogs/body/wheel-arch-repair-panel-replacement-cost-guide "
            "Interim, pending real supplier quote RQ-0077."
        ),
    },
    {
        "canonical_defect": "corrosion_damage",
        "category": "cosmetic",
        "vehicle_class": "small_sedan",
        "pricing_method": "internal_default",
        "low_estimate": 350,
        "default_estimate": 475,
        "high_estimate": 600,
        "confidence": "low",
        "evidence_source": "PartCatalog - wheel arch repair panel replacement cost guide",
        "evidence_date": TODAY,
        "supplier": "",
        "vehicle_specific": "no",
        "labour_required": "yes",
        "notes": (
            "Same source and figure as medium_suv above - the source gives sedan and "
            "compact SUV together as one figure, not a separate sedan-only number. "
            "Source: https://www.partcatalog.com/blogs/body/wheel-arch-repair-panel-replacement-cost-guide"
        ),
    },
    {
        "canonical_defect": "seat_damage",
        "category": "interior",
        "vehicle_class": "ute",
        "pricing_method": "internal_default",
        "low_estimate": 400,
        "default_estimate": 600,
        "high_estimate": 800,
        "confidence": "low",
        "evidence_source": "ServiceTasker - upholstery repair cost guide (AU)",
        "evidence_date": TODAY,
        "supplier": "",
        "vehicle_specific": "no",
        "labour_required": "yes",
        "notes": (
            "Bench-seat reupholster, $400-800 (AU), priced by the source as its own job "
            "type distinct from bucket-seat reupholstering - utes commonly run a bench "
            "seat. Source: "
            "https://servicetasker.com.au/cost-guides/how-much-does-upholstery-repair-cost "
            "Interim, pending real supplier quote RQ-0074."
        ),
    },
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apply researched, class-specific repair prices.")
    p.add_argument("--dry-run", action="store_true", help="Validate and print without saving.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    schedule = load_pricing_schedule()
    existing_keys = set()
    if not schedule.empty and {"canonical_defect", "vehicle_class"}.issubset(schedule.columns):
        existing_keys = set(
            zip(
                schedule["canonical_defect"].astype(str).str.strip(),
                schedule["vehicle_class"].astype(str).str.strip(),
            )
        )

    new_rows = []
    skipped = []
    for row in RESEARCHED_ROWS:
        key = (row["canonical_defect"], row["vehicle_class"])
        if key in existing_keys:
            skipped.append(key)
            continue
        new_rows.append(row)

    if skipped:
        print("already priced, skipped:")
        for canonical, vehicle_class in skipped:
            print(f"  {canonical} / {vehicle_class}")

    if not new_rows:
        print("\nNothing new to add.")
        return 0

    updated = pd.concat([schedule, pd.DataFrame(new_rows, columns=PRICING_COLUMNS)], ignore_index=True)
    errors = validate_pricing_schedule(updated)
    if errors:
        print("\nVALIDATION FAILED - nothing saved:")
        for error in errors:
            print(f"  {error}")
        return 1

    print(f"\n{len(new_rows)} new row(s) to add:")
    for row in new_rows:
        print(
            f"  {row['canonical_defect']:<20} {row['vehicle_class']:<12} "
            f"${row['low_estimate']:,}-${row['high_estimate']:,} (default ${row['default_estimate']:,}, "
            f"confidence={row['confidence']})"
        )

    if args.dry_run:
        print("\nDRY RUN - not saved.")
        return 0

    save_pricing_schedule(updated)
    print(f"\nSaved. Schedule now has {len(updated)} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
