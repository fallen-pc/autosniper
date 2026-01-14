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

from shared.comps_engine import CompsEngine, parse_currency, parse_numeric
from shared.repair_features import REPAIR_CATEGORIES

DEFAULT_INPUT = ROOT_DIR / "artifacts" / "training_data" / "sold_cars_repairs_enriched.csv"
DEFAULT_OUTPUT = ROOT_DIR / "artifacts" / "training_data" / "sold_training_table.csv"
DEFAULT_SNAPSHOTS = ROOT_DIR / "CSV_data" / "active_snapshots.csv"

STATE_ABBREVIATIONS = ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare sold training table with comps outputs.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Enriched sold CSV path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Destination training CSV.")
    parser.add_argument("--snapshots-path", type=Path, default=DEFAULT_SNAPSHOTS, help="Active snapshot log path.")
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
    working["odometer_numeric"] = working["odometer_reading"].apply(parse_numeric)
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
    if "repair_tags" not in df.columns:
        return df

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
    parsed_series = df["repair_tags"].apply(_parse_tags)
    for tag in tag_columns:
        tag_columns[tag] = parsed_series.apply(lambda tags: 1 if tag in tags else 0)
        df[f"tag_{tag}"] = tag_columns[tag]
    df["total_repair_tags"] = parsed_series.apply(len)
    return df


def add_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    if "date_sold" not in df.columns:
        return df
    dates = pd.to_datetime(df["date_sold"], errors="coerce")
    df["date_sold_parsed"] = dates
    if "year" in df.columns:
        df["vehicle_year_numeric"] = pd.to_numeric(df["year"], errors="coerce")
        df["vehicle_age_years"] = dates.dt.year - df["vehicle_year_numeric"]
    else:
        df["vehicle_age_years"] = None
    df["vehicle_age_years"] = df["vehicle_age_years"].fillna(df["vehicle_age_years"].median())
    df["vehicle_age_years"] = df["vehicle_age_years"].replace(0, pd.NA)
    if "odometer_numeric" in df.columns:
        denom = df["vehicle_age_years"].replace({0: pd.NA})
        df["odometer_per_year"] = df["odometer_numeric"] / denom
    return df


def merge_snapshot_features(df: pd.DataFrame, snapshot_path: Path) -> pd.DataFrame:
    snapshot_path = Path(snapshot_path)
    if not snapshot_path.exists():
        return df
    snapshots = pd.read_csv(snapshot_path, parse_dates=["snapshot_ts"], low_memory=False)
    if snapshots.empty or "url" not in snapshots.columns:
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
    df = merge_snapshot_features(df, args.snapshots_path)
    engine = CompsEngine(df)
    comps_df = engine.run()
    merged = pd.concat([df.reset_index(drop=True), comps_df], axis=1)
    if "sale_price_value" in merged.columns and "comps_p50" in merged.columns:
        merged["comps_error"] = merged["sale_price_value"] - merged["comps_p50"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output, index=False)
    print(f"Training dataset written to {args.output} ({len(merged):,} rows)")


if __name__ == "__main__":
    main()
