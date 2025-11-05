"""Utility to de-duplicate sold_cars.csv on VIN while preferring latest sale data."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


CSV_PATH = Path("CSV_data") / "sold_cars.csv"
DEDUP_BACKUP_PATH = CSV_PATH.with_suffix(".csv.bak")


def parse_price(value: object) -> float | None:
    """Return numeric price from string like '$17,700' or 15450.0."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = re.sub(r"[^\d.]", "", text)
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def build_candidate_date(frame: pd.DataFrame) -> pd.Series:
    """Prefer explicit date_sold, fall back to time_remaining_or_date_sold."""
    primary = pd.to_datetime(frame.get("date_sold"), errors="coerce", utc=True)
    secondary_source = frame.get("time_remaining_or_date_sold")
    if secondary_source is None:
        return primary
    secondary = pd.to_datetime(secondary_source, errors="coerce", utc=True)
    primary = primary.fillna(secondary)
    return primary


def deduplicate_sold(df: pd.DataFrame) -> pd.DataFrame:
    """Return dataframe without duplicate VIN rows, keeping latest entries."""
    df = df.copy()
    df["__candidate_date"] = build_candidate_date(df)
    df["__price_numeric"] = df.apply(lambda row: parse_price(row.get("final_price", row.get("price"))), axis=1)

    df = df.sort_values(
        by=["vin", "__candidate_date", "__price_numeric"],
        ascending=[True, False, False],
        kind="mergesort",
    )
    deduped = df.drop_duplicates(subset=["vin"], keep="first")
    deduped = deduped.drop(columns=["__candidate_date", "__price_numeric"])
    return deduped


def main() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"File not found: {CSV_PATH}")

    df = pd.read_csv(CSV_PATH)
    before_count = len(df)
    if "vin" not in df.columns:
        raise SystemExit("VIN column missing; cannot deduplicate.")

    # Backup original file once.
    if not DEDUP_BACKUP_PATH.exists():
        CSV_PATH.replace(DEDUP_BACKUP_PATH)
        # Reload dataframe from backup to avoid reading from moved file.
        df = pd.read_csv(DEDUP_BACKUP_PATH)

    deduped = deduplicate_sold(df)
    after_count = len(deduped)
    removed = before_count - after_count

    deduped.to_csv(CSV_PATH, index=False)

    print(f"Rows before: {before_count}")
    print(f"Rows after:  {after_count}")
    print(f"Removed:     {removed}")
    if removed > 0:
        print("Backup saved to", DEDUP_BACKUP_PATH)


if __name__ == "__main__":
    main()
