"""Normalize listing CSVs with the shared cleanup rules."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import dataset_path
    from shared.schema import ACTIVE_DETAIL_SCHEMA, STATIC_CANONICAL_SCHEMA
    from shared.sold_cleaning import normalize_listing_fields
    from shared.validators import validate_sold_cars_df, validate_vehicle_static_df
else:  # pragma: no cover
    from shared.data_loader import dataset_path
    from shared.schema import ACTIVE_DETAIL_SCHEMA, STATIC_CANONICAL_SCHEMA
    from shared.sold_cleaning import normalize_listing_fields
    from shared.validators import validate_sold_cars_df, validate_vehicle_static_df


TARGET_FILES = (
    dataset_path("vehicle_static_details.csv"),
    dataset_path("active_vehicle_details.csv"),
    dataset_path("sold_cars.csv"),
    dataset_path("referred_cars.csv"),
)

STRICT_SCHEMA_FILES: dict[str, list[str]] = {
    "vehicle_static_details.csv": STATIC_CANONICAL_SCHEMA,
    "active_vehicle_details.csv": ACTIVE_DETAIL_SCHEMA,
}


class SchemaValidationError(ValueError):
    """Raised when a governed CSV does not match its exact schema."""


def _validate_exact_schema(path: Path, df: pd.DataFrame) -> None:
    expected_columns = STRICT_SCHEMA_FILES.get(path.name)
    if expected_columns is None:
        return

    actual_columns = list(df.columns)
    missing_columns = [column for column in expected_columns if column not in actual_columns]
    extra_columns = [column for column in actual_columns if column not in expected_columns]

    if actual_columns == expected_columns:
        return

    message_lines = [
        f"Schema validation failed for {path}.",
        f"Missing columns: {missing_columns or '[]'}",
        f"Extra columns: {extra_columns or '[]'}",
    ]
    if not missing_columns and not extra_columns:
        message_lines.append("Column order does not match the expected schema exactly.")
    message_lines.append(f"Expected columns: {expected_columns}")
    message_lines.append(f"Actual columns: {actual_columns}")

    message = "\n".join(message_lines)
    print(message)
    raise SchemaValidationError(message)


def _normalize_file(path: Path) -> None:
    if not path.exists():
        print(f"Skip missing file: {path}")
        return
    df = pd.read_csv(path, low_memory=False)
    if df.empty:
        print(f"Skip empty file: {path}")
        return
    _validate_exact_schema(path, df)
    normalized = normalize_listing_fields(df)
    _validate_exact_schema(path, normalized)
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
