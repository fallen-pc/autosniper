"""Normalize listing CSVs with the shared cleanup rules."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import dataset_path
    from shared.sold_cleaning import normalize_listing_fields
    from shared.validators import validate_sold_cars_df, validate_vehicle_static_df
else:  # pragma: no cover
    from shared.data_loader import dataset_path
    from shared.sold_cleaning import normalize_listing_fields
    from shared.validators import validate_sold_cars_df, validate_vehicle_static_df


TARGET_FILES = (
    dataset_path("vehicle_static_details.csv"),
    dataset_path("active_vehicle_details.csv"),
    dataset_path("sold_cars.csv"),
    dataset_path("referred_cars.csv"),
)


def _normalize_file(path: Path) -> None:
    if not path.exists():
        print(f"Skip missing file: {path}")
        return
    df = pd.read_csv(path, low_memory=False)
    if df.empty:
        print(f"Skip empty file: {path}")
        return
    normalized = normalize_listing_fields(df)
    if path.name == "vehicle_static_details.csv":
        normalized, stats = validate_vehicle_static_df(normalized)
        if stats["rows_dropped"]:
            print(f"Validator dropped {stats['rows_dropped']} invalid static rows before write.")
    if path.name == "sold_cars.csv":
        normalized, stats = validate_sold_cars_df(normalized)
        if stats["rows_dropped"]:
            print(f"Validator dropped {stats['rows_dropped']} invalid sold rows before write.")
    normalized.to_csv(path, index=False)
    print(f"Normalized {path} ({len(normalized)} rows).")


def main() -> None:
    for path in TARGET_FILES:
        _normalize_file(path)


if __name__ == "__main__":
    main()
