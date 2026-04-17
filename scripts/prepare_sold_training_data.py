"""Generate the sold-car training dataset with comps outputs and numeric fields."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.comps_engine import CompsEngine, parse_currency, parse_numeric
from shared.repair_features import REPAIR_CATEGORIES
from shared.data_loader import dataset_path

DEFAULT_INPUT = ROOT_DIR / "artifacts" / "training_data" / "sold_cars_repairs_enriched.csv"
DEFAULT_OUTPUT = ROOT_DIR / "artifacts" / "training_data" / "sold_training_table.csv"
DEFAULT_SNAPSHOTS = dataset_path("active_snapshots.csv")
DEFAULT_SNAPSHOT_ARCHIVE_DIR = dataset_path("archives/active_snapshots")

STATE_ABBREVIATIONS = ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare sold training table with comps outputs.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Enriched sold CSV path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Destination training CSV.")
    parser.add_argument("--snapshots-path", type=Path, default=DEFAULT_SNAPSHOTS, help="Active snapshot log path.")
    parser.add_argument(
        "--snapshot-archive-dir",
        type=Path,
        default=DEFAULT_SNAPSHOT_ARCHIVE_DIR,
        help="Archived active snapshot directory.",
    )
    return parser.parse_args()


def extract_state(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    upper = text.upper()
    for state in STATE_ABBREVIATIONS:
        if state in upper:
            return state
    if "," in text:
        return text.split(",")[-1].strip().upper()
    parts = text.split()
    if parts:
        return parts[-1].strip().upper()
    return upper


def prepare_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    if "sale_price" in working.columns:
        working["sale_price_value"] = working["sale_price"].apply(parse_currency)
    else:
        working["sale_price_value"] = pd.NA
    if working["sale_price_value"].isna().all() and "price" in working.columns:
        working["sale_price_value"] = working["price"].apply(parse_currency)
    if "odometer_reading" in working.columns:
        working["odometer_numeric"] = working["odometer_reading"].apply(parse_numeric)
    else:
        working["odometer_numeric"] = pd.NA
    if "bids" in working.columns:
        working["bids_final"] = working["bids"].apply(parse_numeric)
    else:
        working["bids_final"] = pd.Series(0, index=working.index, dtype=float)

    if "location_state" in working.columns:
        location_series = working["location_state"]
    elif "location" in working.columns:
        location_series = working["location"]
    else:
        location_series = pd.Series([""] * len(working), index=working.index)
    working["location_state"] = location_series.apply(extract_state)
    working["bids_final"] = working["bids_final"].fillna(0)
    if "estimated_parts_cost_aud" in working.columns:
        working["estimated_parts_cost_aud"] = working["estimated_parts_cost_aud"].apply(parse_numeric)
    else:
        working["estimated_parts_cost_aud"] = 0.0
    if "repair_severity" in working.columns:
        working["repair_severity"] = working["repair_severity"].apply(parse_numeric)
    else:
        working["repair_severity"] = 0.0
    return working


def add_repair_tag_features(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    if "repair_tags" not in working.columns:
        return working

    def _parse_tags(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(tag).strip() for tag in value if tag]
        if isinstance(value, str):
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, list):
                    return [str(tag).strip() for tag in parsed if tag]
            except (ValueError, SyntaxError):
                try:
                    parsed_json = json.loads(value)
                    if isinstance(parsed_json, list):
                        return [str(tag).strip() for tag in parsed_json if tag]
                except json.JSONDecodeError:
                    pass
            return [part.strip() for part in value.strip("[]").split(",") if part.strip()]
        return []

    tag_columns = {tag: [] for tag in REPAIR_CATEGORIES.keys()}
    parsed_series = working["repair_tags"].apply(_parse_tags)
    for tag in tag_columns:
        tag_columns[tag] = parsed_series.apply(lambda tags: 1 if tag in tags else 0)
        working[f"tag_{tag}"] = tag_columns[tag]
    working["total_repair_tags"] = parsed_series.apply(len)
    return working


def add_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    if "date_sold" not in working.columns:
        return working
    dates = pd.to_datetime(working["date_sold"], errors="coerce")
    working["date_sold_parsed"] = dates
    if "year" in working.columns:
        working["vehicle_year_numeric"] = pd.to_numeric(working["year"], errors="coerce")
        working["vehicle_age_years"] = dates.dt.year - working["vehicle_year_numeric"]
    else:
        working["vehicle_age_years"] = None
    working["vehicle_age_years"] = working["vehicle_age_years"].fillna(working["vehicle_age_years"].median())
    working["vehicle_age_years"] = working["vehicle_age_years"].replace(0, pd.NA)
    if "odometer_numeric" in working.columns:
        denom = working["vehicle_age_years"].replace({0: pd.NA})
        working["odometer_per_year"] = working["odometer_numeric"] / denom
    return working


def _load_snapshot_rows(snapshot_path: Path, archive_dir: Path | None = None) -> pd.DataFrame:
    snapshot_path = Path(snapshot_path)
    frames: list[pd.DataFrame] = []
    if snapshot_path.exists():
        current_snapshots = pd.read_csv(snapshot_path, low_memory=False)
        if not current_snapshots.empty:
            frames.append(current_snapshots)
    if archive_dir is not None:
        archive_path = Path(archive_dir)
        if archive_path.exists():
            for path in sorted(archive_path.glob("active_snapshots_*.csv")):
                archived_snapshots = pd.read_csv(path, low_memory=False)
                if not archived_snapshots.empty:
                    frames.append(archived_snapshots)
    if not frames:
        return pd.DataFrame()
    snapshots = pd.concat(frames, ignore_index=True, sort=False)
    if "snapshot_ts" in snapshots.columns:
        parsed_ts = pd.to_datetime(snapshots["snapshot_ts"], errors="coerce", utc=True)
        snapshots["snapshot_ts"] = parsed_ts.dt.tz_convert(None)
    return snapshots


def merge_snapshot_features(
    df: pd.DataFrame,
    snapshot_path: Path,
    snapshot_archive_dir: Path | None = DEFAULT_SNAPSHOT_ARCHIVE_DIR,
) -> pd.DataFrame:
    snapshots = _load_snapshot_rows(snapshot_path, snapshot_archive_dir)
    if snapshots.empty or "url" not in snapshots.columns:
        return df
    if "snapshot_ts" not in snapshots.columns:
        return df
    snapshots = snapshots.sort_values("snapshot_ts").drop_duplicates(subset=["url"], keep="last")
    rename_map = {
        "price_numeric": "snapshot_price_numeric",
        "bids_numeric": "snapshot_bids_numeric",
        "time_remaining_hours": "snapshot_time_remaining_hours",
        "status": "snapshot_status",
        "location_state": "snapshot_location_state",
    }
    snapshots = snapshots.rename(columns=rename_map)
    merged = df.merge(snapshots, on="url", how="left")
    if "date_sold_parsed" in merged.columns and "snapshot_ts" in merged.columns:
        merged["snapshot_hours_to_close"] = (
            merged["date_sold_parsed"] - merged["snapshot_ts"]
        ).dt.total_seconds() / 3600.0
    return merged


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"Enriched sold dataset not found: {args.input}")
    df = pd.read_csv(args.input, low_memory=False)
    df = prepare_numeric_columns(df)
    df = add_repair_tag_features(df)
    df = add_temporal_features(df)
    df = merge_snapshot_features(df, args.snapshots_path, args.snapshot_archive_dir)
    engine = CompsEngine(df)
    comps_df = engine.run()
    merged = pd.concat([df.reset_index(drop=True), comps_df], axis=1)
    if "sale_price_value" in merged.columns and "comps_p50" in merged.columns:
        merged["comps_error"] = merged["sale_price_value"] - merged["comps_p50"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(merged, args.output, index=False)
    print(f"Training dataset written to {args.output} ({len(merged):,} rows)")


if __name__ == "__main__":
    main()
