"""Draft a prioritised batch of repair-price quote requests for the biggest schedule gaps.

Why
---
repair_pricing_schedule.csv covers almost nothing outside small_hatch because the
quote-drafting tool itself was class-blind (see shared/repair_pricing_schedule.py
and project_memory/02_state/quote_pipeline_class_blindness_fix_2026-08-19.md). This
script uses the now-fixed pipeline to draft requests for the exact (canonical,
vehicle_class) cells that matter most, ranked by real observed listing-hits from
the full 20,406-listing coverage scan.

This DRAFTS ONLY. Every row is written with status="draft" - nothing is sent. Emails
still have to go out through whatever channel you actually use; review the draft
subject/body in repair_quote_requests.csv (or the Quote Requests tab in
pages/19_REPAIR_PRICING.py) before sending anything.

Usage
-----
    python -m scripts.build_repair_quote_batch
    python -m scripts.build_repair_quote_batch --top-n 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from shared.repair_pricing_schedule import (
    QUOTE_COLUMNS,
    REPAIR_PRICING_MATRIX_PATH,
    build_quote_request_body,
    build_quote_request_subject,
    humanize_canonical_defect,
    load_quote_requests,
    load_pricing_schedule,
    next_request_id,
    save_quote_requests,
    suggest_supplier_type,
)

# Grounded in this session's own evidence rather than guessed: Corolla/CX-5 already
# match the tool's existing convention (see prior quote rows); Hilux SR and HiAce
# were the deep, well-evidenced lanes found in the retail exit ledger work.
REPRESENTATIVE_VEHICLE = {
    "small_hatch": "2016 Toyota Corolla hatch",
    "small_sedan": "2016 Toyota Camry sedan",
    "medium_suv": "2016 Mazda CX-5",
    "ute": "2018 Toyota Hilux SR dual-cab ute",
    "van": "2017 Toyota HiAce van",
    "generic": "typical vehicle",
}

# Once a cell has an open request, do not draft a duplicate for it.
OPEN_STATUSES = {"draft", "ready", "sent", "waiting", "replied"}


def top_missing_cells(matrix_path: Path, top_n: int) -> pd.DataFrame:
    matrix = pd.read_csv(matrix_path, low_memory=False)
    missing = matrix[matrix["status"] == "MISSING"].copy()
    missing = missing.sort_values("occurrences", ascending=False)
    return missing.head(top_n)


def already_open(quotes: pd.DataFrame, canonical: str, vehicle_class: str) -> bool:
    if quotes.empty or "canonical_defect" not in quotes.columns:
        return False
    same = (quotes["canonical_defect"].astype(str).str.strip() == canonical) & (
        quotes["vehicle_class"].astype(str).str.strip() == vehicle_class
    )
    if not same.any():
        return False
    return bool(quotes.loc[same, "status"].astype(str).str.strip().isin(OPEN_STATUSES).any())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Draft quote requests for the biggest pricing gaps.")
    p.add_argument("--top-n", type=int, default=20, help="How many (canonical, class) cells to draft (default 20).")
    p.add_argument("--matrix", type=Path, default=REPAIR_PRICING_MATRIX_PATH)
    p.add_argument("--dry-run", action="store_true", help="Print what would be drafted without saving.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.matrix.exists():
        print(f"ERROR: {args.matrix} not found. Run scripts/build_repair_pricing_matrix.py first.")
        return 1

    cells = top_missing_cells(args.matrix, args.top_n)
    total_hits = cells["occurrences"].sum()
    print(f"targeting top {len(cells)} missing cells, {int(total_hits):,} listing-hits")

    quotes = load_quote_requests()
    schedule = load_pricing_schedule()
    priced = set()
    if not schedule.empty and {"canonical_defect", "vehicle_class"}.issubset(schedule.columns):
        priced = set(
            zip(
                schedule["canonical_defect"].astype(str).str.strip(),
                schedule["vehicle_class"].astype(str).str.strip(),
            )
        )

    drafted: list[dict[str, object]] = []
    skipped_open = 0
    skipped_priced = 0

    for _, cell in cells.iterrows():
        canonical = str(cell["canonical_defect"]).strip()
        vehicle_class = str(cell["vehicle_class"]).strip()

        if (canonical, vehicle_class) in priced:
            skipped_priced += 1
            continue
        if already_open(quotes, canonical, vehicle_class):
            skipped_open += 1
            continue

        representative_vehicle = REPRESENTATIVE_VEHICLE.get(vehicle_class, "typical vehicle")
        notes = f"{humanize_canonical_defect(canonical)} - {vehicle_class.replace('_', ' ')} pricing gap"
        subject = build_quote_request_subject(canonical)
        body = build_quote_request_body(canonical, representative_vehicle, notes)

        drafted.append(
            {
                "canonical_defect": canonical,
                "category": str(cell.get("cost_model", "")).strip(),
                "vehicle_class": vehicle_class,
                "representative_vehicle": representative_vehicle,
                "supplier": "",
                "supplier_type": suggest_supplier_type(canonical),
                "contact_method": "",
                "status": "draft",
                "request_date": "",
                "response_date": "",
                "quoted_low": "",
                "quoted_high": "",
                "quoted_default": "",
                "evidence_url": "",
                "draft_subject": subject,
                "draft_body": body,
                "notes": f"Batch-drafted from repair_pricing_matrix.csv, {int(cell['occurrences']):,} listing-hits.",
                "recipient_email": "",
                "last_attempted_date": "",
                "sent_message_id": "",
                "sent_thread_id": "",
                "sent_from": "",
                "response_source": "",
                "response_text": "",
                "response_parse_status": "",
            }
        )

    print(f"already priced (skipped)      : {skipped_priced}")
    print(f"already has an open request   : {skipped_open}")
    print(f"new drafts                    : {len(drafted)}")

    if not drafted:
        print("\nNothing to draft.")
        return 0

    if args.dry_run:
        print("\n=== DRY RUN - not saved ===")
        for row in drafted:
            print(f"  {row['canonical_defect']:<28} {row['vehicle_class']:<12} -> {row['supplier_type']}")
        return 0

    existing = quotes.copy()
    for row in drafted:
        row["request_id"] = next_request_id(existing)
        existing = pd.concat([existing, pd.DataFrame([row], columns=QUOTE_COLUMNS)], ignore_index=True)

    save_quote_requests(existing)
    print(f"\nsaved {len(drafted)} new draft(s) to repair_quote_requests.csv")
    print("Nothing was sent - review drafts before sending through your usual channel.")
    for row in drafted:
        print(f"  {row['request_id']}  {row['canonical_defect']:<28} {row['vehicle_class']:<12} "
              f"({row['supplier_type']})  -> {row['representative_vehicle']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
