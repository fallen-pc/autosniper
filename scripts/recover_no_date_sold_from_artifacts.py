"""Recover missing sold dates from local sold-history artifacts."""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.atomic_csv import write_dataframe_csv_atomic
from scripts.build_sold_cars_all_ledger import (
    build_sold_cars_all_ledger,
    ledger_exclusions,
)
from shared.data_loader import dataset_path
from shared.validators import R, validate_sold_cars_df


DEFAULT_STRICT_SOLD_PATH = dataset_path("sold_cars.csv")
DEFAULT_HISTORICAL_SOLD_PATH = dataset_path("sold_cars_historical.csv")
DEFAULT_LEDGER_PATH = dataset_path("sold_cars_all.csv")
DEFAULT_LEDGER_REPORT_PATH = dataset_path("model_audit/sold_cars_all_ledger_report.csv")
DEFAULT_LEDGER_EXCLUSIONS_PATH = dataset_path("model_audit/sold_cars_all_ledger_exclusions.csv")
DEFAULT_RECOVERY_REPORT_PATH = dataset_path("model_audit/no_date_sold_local_date_recovery_report.csv")
DEFAULT_UNRESOLVED_PATH = dataset_path("model_audit/no_date_sold_unresolved_after_local_recovery.csv")
DEFAULT_SOURCES = (
    Path("artifacts/training_data/sold_cars.csv"),
    Path("artifacts/training_data/sold_cars_repairs_enriched.csv"),
    Path("artifacts/training_data/sold_training_table.csv"),
)
DATE_COLUMNS = ("date_sold_parsed", "date_sold")


@dataclass(frozen=True)
class Recovery:
    url: str
    date_sold: str
    source_path: str
    source_column: str


def _normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat", "n/a"} else text


def _backup(path: Path, timestamp: str) -> Path | None:
    if not path.exists():
        return None
    backup_path = path.with_name(f"{path.stem}.pre_no_date_recovery_{timestamp}{path.suffix}")
    shutil.copy2(path, backup_path)
    return backup_path


def collect_recoveries(
    no_date_urls: set[str],
    source_paths: list[Path],
) -> dict[str, Recovery]:
    recoveries: dict[str, Recovery] = {}
    for source_path in source_paths:
        if not source_path.exists():
            continue
        source = pd.read_csv(source_path, low_memory=False)
        if "url" not in source.columns:
            continue
        hit = source[source["url"].fillna("").astype(str).str.strip().isin(no_date_urls)]
        for _, row in hit.iterrows():
            url = _normalize_text(row.get("url"))
            if not url or url in recoveries:
                continue
            for column in DATE_COLUMNS:
                if column not in hit.columns:
                    continue
                date_sold = _normalize_text(row.get(column))
                if not date_sold:
                    continue
                recoveries[url] = Recovery(
                    url=url,
                    date_sold=date_sold,
                    source_path=str(source_path),
                    source_column=column,
                )
                break
    return recoveries


def _strict_ready_frame(rows: pd.DataFrame) -> tuple[pd.DataFrame, set[str]]:
    if rows.empty:
        return rows.copy(), set()
    cleaned, _ = validate_sold_cars_df(rows, strict=True)
    return cleaned, set(cleaned["url"].fillna("").astype(str).str.strip())


def recover_no_date_sold(
    *,
    strict_sold: pd.DataFrame,
    ledger: pd.DataFrame,
    source_paths: list[Path],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    strict_urls = set(strict_sold.get("url", pd.Series(dtype=str)).fillna("").astype(str).str.strip())
    no_date = ledger[
        (ledger.get("ledger_source", "") == "historical_sold")
        & (ledger.get("strict_exclusion_reason", "") == R.NO_DATE_SOLD)
    ].copy()
    no_date_urls = set(no_date["url"].fillna("").astype(str).str.strip()) - strict_urls
    recoveries = collect_recoveries(no_date_urls, source_paths)

    recovered_rows = no_date[no_date["url"].fillna("").astype(str).str.strip().isin(recoveries)].copy()
    for idx, row in recovered_rows.iterrows():
        recovery = recoveries[_normalize_text(row.get("url"))]
        recovered_rows.at[idx, "date_sold"] = recovery.date_sold

    strict_ready, strict_ready_urls = _strict_ready_frame(recovered_rows)

    report_rows: list[dict[str, object]] = []
    for url, recovery in sorted(recoveries.items()):
        report_rows.append(
            {
                "url": url,
                "recovered_date_sold": recovery.date_sold,
                "source_path": recovery.source_path,
                "source_column": recovery.source_column,
                "promoted_to_strict": url in strict_ready_urls,
                "rejection_reason": "" if url in strict_ready_urls else "validator_rejected_after_date_recovery",
            }
        )
    report = pd.DataFrame(report_rows)

    if strict_ready.empty:
        updated_strict = strict_sold.copy()
    else:
        promoted = strict_ready.copy()
        for column in strict_sold.columns:
            if column not in promoted.columns:
                promoted[column] = ""
        promoted = promoted[list(strict_sold.columns)]
        updated_strict = pd.concat([strict_sold, promoted], ignore_index=True, sort=False)
        updated_strict = updated_strict.drop_duplicates(subset=["url"], keep="first").copy()

    unresolved_urls = no_date_urls - strict_ready_urls
    unresolved = no_date[no_date["url"].fillna("").astype(str).str.strip().isin(unresolved_urls)].copy()
    return updated_strict, report, unresolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recover no-date sold ledger rows from local sold-history artifacts.")
    parser.add_argument("--strict-sold", type=Path, default=DEFAULT_STRICT_SOLD_PATH)
    parser.add_argument("--historical-sold", type=Path, default=DEFAULT_HISTORICAL_SOLD_PATH)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--ledger-report", type=Path, default=DEFAULT_LEDGER_REPORT_PATH)
    parser.add_argument("--ledger-exclusions", type=Path, default=DEFAULT_LEDGER_EXCLUSIONS_PATH)
    parser.add_argument("--recovery-report", type=Path, default=DEFAULT_RECOVERY_REPORT_PATH)
    parser.add_argument("--unresolved-report", type=Path, default=DEFAULT_UNRESOLVED_PATH)
    parser.add_argument("--source", type=Path, action="append", dest="sources")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args(argv)

    source_paths = args.sources or list(DEFAULT_SOURCES)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    strict = pd.read_csv(args.strict_sold, low_memory=False) if args.strict_sold.exists() else pd.DataFrame()
    ledger = pd.read_csv(args.ledger, low_memory=False) if args.ledger.exists() else pd.DataFrame()
    historical = pd.read_csv(args.historical_sold, low_memory=False) if args.historical_sold.exists() else pd.DataFrame()

    backups = []
    if not args.no_backup:
        for path in (args.strict_sold, args.ledger):
            backup = _backup(path, timestamp)
            if backup:
                backups.append(str(backup))

    updated_strict, recovery_report, unresolved = recover_no_date_sold(
        strict_sold=strict,
        ledger=ledger,
        source_paths=source_paths,
    )

    write_dataframe_csv_atomic(updated_strict, args.strict_sold, index=False)
    write_dataframe_csv_atomic(recovery_report, args.recovery_report, index=False)
    write_dataframe_csv_atomic(unresolved, args.unresolved_report, index=False)

    rebuilt_ledger, ledger_report = build_sold_cars_all_ledger(
        strict_sold=updated_strict,
        historical_sold=historical,
    )
    write_dataframe_csv_atomic(rebuilt_ledger, args.ledger, index=False)
    write_dataframe_csv_atomic(ledger_report, args.ledger_report, index=False)
    write_dataframe_csv_atomic(ledger_exclusions(rebuilt_ledger), args.ledger_exclusions, index=False)

    promoted = int(recovery_report["promoted_to_strict"].sum()) if "promoted_to_strict" in recovery_report else 0
    print(
        "[recover-no-date-sold] "
        f"recoverable={len(recovery_report)} "
        f"promoted={promoted} "
        f"unresolved={len(unresolved)} "
        f"strict_rows_before={len(strict)} "
        f"strict_rows_after={len(updated_strict)} "
        f"backups={backups}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
