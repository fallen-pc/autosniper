"""Re-scrape missing condition notes across datasets."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.data_loader import dataset_path
    from shared.validators import validate_sold_cars_df, validate_vehicle_static_df
    from scripts.extract_vehicle_details import process_links
else:  # pragma: no cover
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.data_loader import dataset_path
    from shared.validators import validate_sold_cars_df, validate_vehicle_static_df
    from scripts.extract_vehicle_details import process_links


DEFAULT_DATASETS = [
    "vehicle_static_details.csv",
    "sold_cars.csv",
]
LEGACY_DIR = dataset_path("ai_analysis_ready")
SNAPSHOT_COLUMNS = [
    "general_condition",
]
RENAMED_COLUMNS = {
    "Body Type": "body_type",
    "No. of Seats": "no_of_seats",
    "Build Date": "build_date",
    "Compliance Date": "compliance_date",
    "VIN": "vin",
    "Registration No": "rego_no",
    "Registration State": "rego_state",
    "Registration Expiry Date": "rego_expiry",
    "No. of Plates": "no_of_plates",
    "No. of Cylinders": "no_of_cylinders",
    "Engine Capacity": "engine_capacity",
    "Fuel Type": "fuel_type",
    "Transmission": "transmission",
    "Indicated Odometer Reading": "odometer_reading",
    "Odometer Measurement": "odometer_unit",
    "Exterior Colour": "exterior_colour",
    "Interior Colour": "interior_colour",
    "Key": "key",
    "Spare Key": "spare_key",
    "Owners Manual": "owners_manual",
    "Service History": "service_history",
    "Engine Turns Over": "engine_turns_over",
    "Location": "location",
    "date": "time_remaining_or_date_sold",
}
MISSING_VALUES = {"", "n/a", "na", "nan", "none", "null"}


def atomic_write(df: pd.DataFrame, path: Path) -> None:
    write_dataframe_csv_atomic(df, path, index=False)


def normalize_legacy_frame(df: pd.DataFrame, reference_columns: list[str]) -> pd.DataFrame:
    df = df.rename(columns=RENAMED_COLUMNS)
    if "general_condition" not in df.columns:
        df["general_condition"] = pd.NA
    for column in reference_columns:
        if column not in df.columns:
            df[column] = pd.NA
    ordered = reference_columns + [col for col in df.columns if col not in reference_columns]
    return df[ordered]


def normalize_legacy_file(path: Path, reference_columns: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = normalize_legacy_frame(df, reference_columns)
    atomic_write(df, path)
    return df


def build_dataset_list(
    dataset_paths: Iterable[str],
    include_legacy: bool,
    legacy_pattern: str,
) -> list[tuple[Path, pd.DataFrame]]:
    datasets: list[tuple[Path, pd.DataFrame]] = []
    reference_path = dataset_path("sold_cars.csv")
    if not reference_path.exists():
        raise FileNotFoundError(f"Sold dataset not found at {reference_path}")
    reference_columns = pd.read_csv(reference_path, nrows=0).columns.tolist()

    for relative in dataset_paths:
        path = dataset_path(relative)
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if "general_condition" not in df.columns:
            df["general_condition"] = pd.NA
        datasets.append((path, df))

    if include_legacy and LEGACY_DIR.exists():
        for legacy_file in sorted(LEGACY_DIR.glob(legacy_pattern)):
            df = normalize_legacy_file(legacy_file, reference_columns)
            datasets.append((legacy_file, df))
    return datasets


def is_missing(value: object) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    return text.lower() in MISSING_VALUES


def collect_missing_urls(datasets: list[tuple[Path, pd.DataFrame]]) -> dict[str, list[tuple[int, Path]]]:
    missing_map: dict[str, list[tuple[int, Path]]] = {}
    for path, df in datasets:
        if "url" not in df.columns:
            continue
        condition_series = df["general_condition"].fillna("").astype(str).str.strip()
        mask = condition_series.apply(lambda text: text.lower() in MISSING_VALUES)
        missing_rows = df[mask]
        for idx, url in missing_rows["url"].items():
            normalized = str(url).strip()
            if not normalized:
                continue
            missing_map.setdefault(normalized, []).append((idx, path))
    return missing_map


def update_datasets(
    datasets: list[tuple[Path, pd.DataFrame]],
    scraped_rows: dict[str, dict],
) -> list[Path]:
    touched: set[Path] = set()
    scraped_fields = set(SNAPSHOT_COLUMNS)
    for path, df in datasets:
        if "url" not in df.columns:
            continue
        url_series = df["url"].astype(str).str.strip()
        if not url_series.any():
            continue
        matching_urls = url_series[url_series.isin(scraped_rows.keys())]
        if matching_urls.empty:
            continue
        for column in SNAPSHOT_COLUMNS:
            if column not in df.columns:
                df[column] = pd.NA
        for idx, url in matching_urls.items():
            payload = scraped_rows.get(url)
            if not payload:
                continue
            for column in scraped_fields:
                new_value = payload.get(column)
                if new_value and (is_missing(df.at[idx, column]) or column == "general_condition"):
                    df.at[idx, column] = new_value
                    touched.add(path)
    return list(touched)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing condition notes by re-scraping listing URLs.")
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=DEFAULT_DATASETS,
        help="Dataset filenames (relative to CSV_data) to update.",
    )
    parser.add_argument(
        "--legacy-pattern",
        default="soldcars*.csv",
        help="Glob for ai_analysis_ready legacy files to normalize (default: soldcars*.csv)",
    )
    parser.add_argument(
        "--skip-legacy",
        action="store_true",
        help="Do not process ai_analysis_ready legacy CSVs.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=80,
        help="Number of URLs per scraping batch.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Identify URLs needing backfill but skip scraping and writing.",
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        default=None,
        help="Only process the first N missing URLs (useful for smoke tests).",
    )

    args = parser.parse_args()
    datasets = build_dataset_list(args.datasets, not args.skip_legacy, args.legacy_pattern)
    if not datasets:
        print("No datasets loaded. Exiting.")
        return

    missing_map = collect_missing_urls(datasets)
    missing_urls = sorted(missing_map.keys())
    if not missing_urls:
        print("Every dataset already has general condition notes.")
        return
    if args.max_urls:
        missing_urls = missing_urls[: args.max_urls]

    print(f"Found {len(missing_urls)} URLs missing condition data.")
    if args.dry_run:
        for url in missing_urls[:20]:
            print(f"- {url} ({len(missing_map[url])} occurrence(s))")
        if len(missing_urls) > 20:
            print("... (truncated)")
        return

    results, skipped = process_links(missing_urls)
    if skipped:
        print(f"{len(skipped)} URLs could not be scraped.")
    if not results:
        print("No condition data scraped; aborting.")
        return

    scraped_map = {}
    for entry in results:
        url = str(entry.get("url", "")).strip()
        if not url:
            continue
        payload = {field: entry.get(field) for field in SNAPSHOT_COLUMNS}
        scraped_map[url] = payload

    touched_paths = update_datasets(datasets, scraped_map)
    if not touched_paths:
        print("No datasets were updated.")
        return

    for path, df in datasets:
        if path not in touched_paths:
            continue
        if path.name == "vehicle_static_details.csv":
            df, stats = validate_vehicle_static_df(df)
            if stats["rows_dropped"]:
                print(f"Validator dropped {stats['rows_dropped']} invalid static rows before write.")
        elif path.name == "sold_cars.csv":
            df, stats = validate_sold_cars_df(df)
            if stats["rows_dropped"]:
                print(f"Validator dropped {stats['rows_dropped']} invalid sold rows before write.")
        atomic_write(df, path)
        print(f"Updated {path.relative_to(Path.cwd()) if path.is_absolute() else path}")


if __name__ == "__main__":
    main()
