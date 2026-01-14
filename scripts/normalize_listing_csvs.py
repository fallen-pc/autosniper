"""Normalize listing CSVs with the shared cleanup rules."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import DATA_DIR
    from shared.sold_cleaning import normalize_listing_fields
else:  # pragma: no cover
    from shared.data_loader import DATA_DIR
    from shared.sold_cleaning import normalize_listing_fields


TARGET_FILES = (
    DATA_DIR / "vehicle_static_details.csv",
    DATA_DIR / "active_vehicle_details.csv",
    DATA_DIR / "sold_cars.csv",
    DATA_DIR / "referred_cars.csv",
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
    normalized.to_csv(path, index=False)
    print(f"Normalized {path} ({len(normalized)} rows).")


def main() -> None:
    for path in TARGET_FILES:
        _normalize_file(path)


if __name__ == "__main__":
    main()
