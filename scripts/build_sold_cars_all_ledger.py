"""Build a complete sold ledger separate from the strict model-ready sold CSV."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

import scripts.update_master as update_master
from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.data_loader import dataset_path
from shared.governance import SOLD_DETAIL_SCHEMA
from shared.validators import validate_sold_cars_df


DEFAULT_STRICT_SOLD_PATH = dataset_path("sold_cars.csv")
DEFAULT_HISTORICAL_SOLD_PATH = dataset_path("sold_cars_historical.csv")
DEFAULT_OUTPUT_PATH = dataset_path("sold_cars_all.csv")
DEFAULT_REPORT_PATH = dataset_path("model_audit/sold_cars_all_ledger_report.csv")
DEFAULT_EXCLUSIONS_PATH = dataset_path("model_audit/sold_cars_all_ledger_exclusions.csv")

LEDGER_COLUMNS = list(
    dict.fromkeys(
        SOLD_DETAIL_SCHEMA
        + [
            "ledger_source",
            "strict_sold_ready",
            "strict_exclusion_reason",
        ]
    )
)


def _url_series(df: pd.DataFrame) -> pd.Series:
    if "url" not in df.columns:
        return pd.Series("", index=df.index, dtype=str)
    return df["url"].fillna("").astype(str).str.strip()


def _normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "n/a"} else text


def _parse_money(value: object) -> float | None:
    text = _normalize_text(value)
    if not text:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", text)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _validator_reason(row: pd.Series) -> str:
    reasons: list[str] = []
    price = _parse_money(row.get("price"))
    if price is None or price <= 0:
        reasons.append("bad_price")
    date = pd.to_datetime(row.get("date_sold"), errors="coerce")
    if pd.isna(date):
        reasons.append("bad_date_sold")
    odometer = pd.to_numeric(row.get("odometer_reading"), errors="coerce")
    if pd.isna(odometer):
        reasons.append("missing_odometer")
    elif odometer < 1000 or odometer > 700000:
        reasons.append("odometer_out_of_range")
    bids = pd.to_numeric(row.get("bids"), errors="coerce")
    if not pd.isna(bids) and bids < 0:
        reasons.append("negative_bids")
    return "|".join(reasons) or "validator_rejected"


def _prepare_without_discard_side_effects(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if rows.empty:
        return pd.DataFrame(columns=SOLD_DETAIL_SCHEMA), pd.DataFrame()
    original_append = update_master._append_sold_discard_log
    update_master._append_sold_discard_log = lambda records: None
    try:
        _, failures = update_master._clean_sold_rows(rows)
        prepared = update_master._prepare_sold_rows(rows)
    finally:
        update_master._append_sold_discard_log = original_append
    return prepared, pd.DataFrame(failures)


def build_sold_cars_all_ledger(
    *,
    strict_sold: pd.DataFrame,
    historical_sold: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    strict = strict_sold.copy()
    for column in LEDGER_COLUMNS:
        if column not in strict.columns:
            strict[column] = ""
    strict["ledger_source"] = "current_strict_sold"
    strict["strict_sold_ready"] = True
    strict["strict_exclusion_reason"] = ""
    strict_urls = set(_url_series(strict))

    historical = historical_sold.copy()
    historical["_url_norm"] = _url_series(historical)
    historical_missing = historical[~historical["_url_norm"].isin(strict_urls)].drop(columns=["_url_norm"]).copy()

    prepared, cleaner_failures = _prepare_without_discard_side_effects(historical_missing)
    validated, _ = validate_sold_cars_df(prepared, strict=True) if not prepared.empty else (prepared, {})
    prepared_urls = set(_url_series(prepared))
    validated_urls = set(_url_series(validated))

    cleaner_failure_by_url: dict[str, str] = {}
    if not cleaner_failures.empty:
        for _, row in cleaner_failures.iterrows():
            url = _normalize_text(row.get("url"))
            reason = _normalize_text(row.get("reason_code")) or "cleaner_rejected"
            if not url:
                continue
            cleaner_failure_by_url[url] = reason

    ledger_extra = historical_missing.copy()
    for column in LEDGER_COLUMNS:
        if column not in ledger_extra.columns:
            ledger_extra[column] = ""
    ledger_extra["ledger_source"] = "historical_sold"
    ledger_extra["strict_sold_ready"] = ledger_extra["url"].astype(str).isin(validated_urls)

    validator_reason_by_url: dict[str, str] = {}
    if not prepared.empty:
        prepared_rejected = prepared[~_url_series(prepared).isin(validated_urls)].copy()
        for _, row in prepared_rejected.iterrows():
            validator_reason_by_url[_normalize_text(row.get("url"))] = _validator_reason(row)

    def reason_for(row: pd.Series) -> str:
        if bool(row.get("strict_sold_ready")):
            return ""
        url = _normalize_text(row.get("url"))
        if url in validator_reason_by_url:
            return validator_reason_by_url[url]
        if url in cleaner_failure_by_url:
            return cleaner_failure_by_url[url]
        if url not in prepared_urls:
            return "cleaner_rejected"
        return "validator_rejected"

    ledger_extra["strict_exclusion_reason"] = ledger_extra.apply(reason_for, axis=1)
    ledger = pd.concat(
        [strict[LEDGER_COLUMNS], ledger_extra[LEDGER_COLUMNS]],
        ignore_index=True,
        sort=False,
    )
    ledger = ledger.drop_duplicates(subset=["url"], keep="first").copy()

    report = pd.DataFrame(
        [
            {
                "current_strict_rows": len(strict_sold),
                "historical_rows": len(historical_sold),
                "historical_missing_from_strict": len(historical_missing),
                "ledger_rows": len(ledger),
                "ledger_only_rows": int((ledger["ledger_source"] == "historical_sold").sum()),
                "strict_ready_rows": int(ledger["strict_sold_ready"].astype(bool).sum()),
                "ledger_only_not_strict_ready": int(
                    ((ledger["ledger_source"] == "historical_sold") & ~ledger["strict_sold_ready"].astype(bool)).sum()
                ),
                "exclusion_reasons": json.dumps(
                    ledger.loc[
                        (ledger["ledger_source"] == "historical_sold") & ~ledger["strict_sold_ready"].astype(bool),
                        "strict_exclusion_reason",
                    ]
                    .value_counts()
                    .to_dict(),
                    sort_keys=True,
                ),
            }
        ]
    )
    return ledger, report


def ledger_exclusions(ledger: pd.DataFrame) -> pd.DataFrame:
    """Return row-level ledger entries that are not ready for strict sold history."""
    if ledger.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    mask = (ledger["ledger_source"] == "historical_sold") & ~ledger["strict_sold_ready"].astype(bool)
    columns = [column for column in LEDGER_COLUMNS if column in ledger.columns]
    return ledger.loc[mask, columns].copy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build sold_cars_all.csv as a complete ledger including non-model-ready sold rows.")
    parser.add_argument("--strict-sold", type=Path, default=DEFAULT_STRICT_SOLD_PATH)
    parser.add_argument("--historical-sold", type=Path, default=DEFAULT_HISTORICAL_SOLD_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--exclusions", type=Path, default=DEFAULT_EXCLUSIONS_PATH)
    args = parser.parse_args(argv)

    strict = pd.read_csv(args.strict_sold, low_memory=False) if args.strict_sold.exists() else pd.DataFrame()
    historical = pd.read_csv(args.historical_sold, low_memory=False) if args.historical_sold.exists() else pd.DataFrame()
    ledger, report = build_sold_cars_all_ledger(strict_sold=strict, historical_sold=historical)
    write_dataframe_csv_atomic(ledger, args.output, index=False)
    write_dataframe_csv_atomic(report, args.report, index=False)
    exclusions = ledger_exclusions(ledger)
    write_dataframe_csv_atomic(exclusions, args.exclusions, index=False)
    row = report.iloc[0].to_dict()
    print(
        "[sold-ledger] "
        f"strict_rows={row['current_strict_rows']} "
        f"historical_missing={row['historical_missing_from_strict']} "
        f"ledger_rows={row['ledger_rows']} "
        f"ledger_only_not_strict_ready={row['ledger_only_not_strict_ready']} "
        f"output={args.output} "
        f"report={args.report} "
        f"exclusions={args.exclusions}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
