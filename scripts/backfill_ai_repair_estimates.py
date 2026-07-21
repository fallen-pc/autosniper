"""Backfill missing AI valuation repair low/high estimate fields.

The valuation cache mixes current rows with older simulated proof rows. Some
older rows predate repair range fields, and hard-avoid rows intentionally wrote
only the blunt repair_estimate. This script fills missing low/high fields from
source condition text where possible, falling back to repair_estimate only when
no condition evidence exists.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.comps_engine import parse_currency
from shared.data_loader import dataset_path
from shared.repair_pricing import assess_repairs


DEFAULT_VALUATIONS_PATH = dataset_path("ai_listing_valuations.csv")
DEFAULT_REPORT_PATH = dataset_path("model_audit/ai_repair_estimate_backfill_report.csv")
DEFAULT_SOURCE_PATHS = (
    dataset_path("sold_cars.csv"),
    dataset_path("sold_cars_historical.csv"),
    dataset_path("referred_cars.csv"),
    dataset_path("active_vehicle_details.csv"),
    dataset_path("vehicle_static_details.csv"),
)

REPAIR_COLUMNS = (
    "repair_estimate_low",
    "repair_estimate_high",
    "repair_estimate_low_value",
    "repair_estimate_high_value",
)


@dataclass(frozen=True)
class RepairBackfill:
    low: float
    high: float
    source: str


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "none", "n/a", "<na>"}


def _format_currency(value: float | int | None) -> str | None:
    if value is None or pd.isna(value):
        return None
    return f"${float(value):,.0f}"


def _parse_money(value: object) -> float | None:
    if _is_blank(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    parsed = parse_currency(value)
    if parsed is None or pd.isna(parsed):
        return None
    return float(parsed)


def _first_nonblank(row: pd.Series, fields: Iterable[str]) -> object:
    for field in fields:
        if field in row.index and not _is_blank(row.get(field)):
            return row.get(field)
    return None


def _load_condition_by_url(source_paths: Iterable[Path]) -> dict[str, str]:
    condition_by_url: dict[str, str] = {}
    for source_path in source_paths:
        if not source_path.exists():
            continue
        source = pd.read_csv(source_path, low_memory=False)
        if "url" not in source.columns or "general_condition" not in source.columns:
            continue
        for _, row in source[["url", "general_condition"]].dropna(subset=["url"]).iterrows():
            url = str(row.get("url") or "").strip()
            condition = row.get("general_condition")
            if not url or _is_blank(condition):
                continue
            condition_by_url[url] = str(condition)
    return condition_by_url


def _vehicle_value(row: pd.Series) -> float | None:
    return _parse_money(_first_nonblank(row, ("resale_mid_value", "resale_mid", "carsales_price_estimate")))


def _repair_from_condition(row: pd.Series, condition_by_url: dict[str, str]) -> RepairBackfill | None:
    url = str(row.get("url") or "").strip()
    condition = condition_by_url.get(url)
    if _is_blank(condition):
        return None
    assessment = assess_repairs(str(condition), vehicle_value=_vehicle_value(row))
    low = assessment.total_cost_low
    high = assessment.total_cost_high
    if low is None or pd.isna(low):
        low = assessment.total_cost
    if high is None or pd.isna(high):
        high = assessment.total_cost
    if low is None or high is None or pd.isna(low) or pd.isna(high):
        return None
    return RepairBackfill(float(low), float(high), "source_general_condition")


def _repair_from_existing_estimate(row: pd.Series) -> RepairBackfill | None:
    estimate = _parse_money(row.get("repair_estimate"))
    if estimate is None:
        return None
    return RepairBackfill(estimate, estimate, "repair_estimate_fallback")


def _needs_repair_range_backfill(row: pd.Series) -> bool:
    return any(column not in row.index or _is_blank(row.get(column)) for column in REPAIR_COLUMNS)


def backfill_repair_estimates(
    valuations: pd.DataFrame,
    *,
    condition_by_url: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = valuations.copy()
    for column in REPAIR_COLUMNS:
        if column not in working.columns:
            working[column] = pd.NA

    report_rows: list[dict[str, object]] = []
    for index, row in working.iterrows():
        if not _needs_repair_range_backfill(row):
            continue

        backfill = _repair_from_condition(row, condition_by_url) or _repair_from_existing_estimate(row)
        if backfill is None:
            continue

        old_values = {column: row.get(column) for column in REPAIR_COLUMNS}
        if _is_blank(row.get("repair_estimate_low")):
            working.at[index, "repair_estimate_low"] = _format_currency(backfill.low)
        if _is_blank(row.get("repair_estimate_high")):
            working.at[index, "repair_estimate_high"] = _format_currency(backfill.high)
        if _is_blank(row.get("repair_estimate_low_value")):
            working.at[index, "repair_estimate_low_value"] = backfill.low
        if _is_blank(row.get("repair_estimate_high_value")):
            working.at[index, "repair_estimate_high_value"] = backfill.high

        report_rows.append(
            {
                "url": row.get("url"),
                "analysis_context": row.get("analysis_context"),
                "computed_verdict": row.get("computed_verdict"),
                "repair_backfill_source": backfill.source,
                "old_repair_estimate_low": old_values["repair_estimate_low"],
                "old_repair_estimate_high": old_values["repair_estimate_high"],
                "old_repair_estimate_low_value": old_values["repair_estimate_low_value"],
                "old_repair_estimate_high_value": old_values["repair_estimate_high_value"],
                "new_repair_estimate_low": working.at[index, "repair_estimate_low"],
                "new_repair_estimate_high": working.at[index, "repair_estimate_high"],
                "new_repair_estimate_low_value": working.at[index, "repair_estimate_low_value"],
                "new_repair_estimate_high_value": working.at[index, "repair_estimate_high_value"],
            }
        )

    return working, pd.DataFrame(report_rows)


def _backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return path.with_name(f"{path.stem}.pre_repair_backfill_{stamp}{path.suffix}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill missing repair estimate range fields in ai_listing_valuations.csv.")
    parser.add_argument("--valuations", type=Path, default=DEFAULT_VALUATIONS_PATH)
    parser.add_argument("--source", type=Path, action="append", default=None, help="CSV with url and general_condition. Repeatable.")
    parser.add_argument("--output", type=Path, default=None, help="Write updated valuations here. Defaults to --valuations with --write.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--write", action="store_true", help="Write the updated valuations CSV. Without this, only a report is written.")
    args = parser.parse_args(argv)

    source_paths = tuple(args.source) if args.source else DEFAULT_SOURCE_PATHS
    valuations = pd.read_csv(args.valuations, low_memory=False)
    condition_by_url = _load_condition_by_url(source_paths)
    updated, report = backfill_repair_estimates(valuations, condition_by_url=condition_by_url)

    changed_rows = len(report)
    if changed_rows:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        write_dataframe_csv_atomic(report, args.report, index=False)

    if args.write and changed_rows:
        output_path = args.output or args.valuations
        if output_path == args.valuations:
            backup = _backup_path(args.valuations)
            shutil.copy2(args.valuations, backup)
            print(f"[repair-backfill] backup={backup}")
        write_dataframe_csv_atomic(updated, output_path, index=False)
        print(f"[repair-backfill] wrote={output_path}")
    elif args.output and changed_rows:
        write_dataframe_csv_atomic(updated, args.output, index=False)
        print(f"[repair-backfill] wrote_preview={args.output}")

    source_counts = report["repair_backfill_source"].value_counts().to_dict() if not report.empty else {}
    print(
        "[repair-backfill] "
        f"rows={len(valuations)} "
        f"changed_rows={changed_rows} "
        f"condition_sources={len(condition_by_url)} "
        f"sources={source_counts} "
        f"report={args.report}"
    )
    if not args.write and not args.output:
        print("[repair-backfill] dry run only; pass --write to update valuations.")
    if not changed_rows:
        print("[repair-backfill] no missing repair ranges found; existing report left unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
