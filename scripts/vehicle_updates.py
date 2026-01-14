from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from shared.data_loader import dataset_path, upload_remote_data_bundle


def _atomic_write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(suffix=path.suffix or ".csv")
    os.close(fd)
    try:
        df.to_csv(temp_path, index=False)
        shutil.move(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def coerce_price(value: Any) -> float | None:
    """Parse currency-like inputs such as '$12,500' or '12500' into floats."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace("$", "").replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _ensure_manual_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "manual_carsales_min" not in df.columns:
        df["manual_carsales_min"] = None
    if "manual_carsales_max" not in df.columns:
        df["manual_carsales_max"] = None
    if "manual_carsales_avg" not in df.columns:
        df["manual_carsales_avg"] = None
    if "manual_carsales_sold_30d" not in df.columns:
        df["manual_carsales_sold_30d"] = None
    if "manual_recent_sales_30d" not in df.columns:
        df["manual_recent_sales_30d"] = None
    if "manual_carsales_count" not in df.columns:
        df["manual_carsales_count"] = None
    if "manual_carsales_table" not in df.columns:
        df["manual_carsales_table"] = None
    if "manual_carsales_estimate" not in df.columns:
        df["manual_carsales_estimate"] = None
    if "carsales_skipped" not in df.columns:
        df["carsales_skipped"] = False
    return df


def _manual_avg_from_values(min_val: Any, max_val: Any) -> float | None:
    min_price = coerce_price(min_val)
    max_price = coerce_price(max_val)
    if min_price is None and max_price is None:
        return None
    if min_price is None:
        return max_price
    if max_price is None:
        return min_price
    return (min_price + max_price) / 2.0


def _apply_updates_to_file(path: Path, url_key: str, updates: dict[str, Any]) -> bool:
    if not path.exists():
        return False
    try:
        df = pd.read_csv(path)
    except Exception:
        return False

    df = _ensure_manual_columns(df)
    if "url" not in df.columns:
        return False

    url_series = df["url"].astype(str).str.strip().str.casefold()
    target_url = url_key.strip().casefold()
    mask = url_series == target_url
    if not mask.any():
        return False

    for column, value in updates.items():
        if column not in df.columns:
            df[column] = None
        df.loc[mask, column] = value
    if "manual_carsales_avg" in df.columns:
        df.loc[mask, "manual_carsales_avg"] = df.loc[mask].apply(
            lambda row: _manual_avg_from_values(
                row.get("manual_carsales_min"), row.get("manual_carsales_max")
            ),
            axis=1,
        )

    _atomic_write(df, path)
    return True


def _update_ai_manual_cache(
    url_key: str,
    manual_min: float | None,
    manual_max: float | None,
    sold_last_30d: int | None,
    skipped: bool | None,
) -> bool:
    """Persist manual Carsales inputs inside ai_listing_valuations.csv for durability."""
    path = dataset_path("ai_listing_valuations.csv")
    if path.exists():
        df = pd.read_csv(path)
    else:
        df = pd.DataFrame(columns=["url"])

    df = _ensure_manual_columns(df)
    if "url" not in df.columns:
        df["url"] = None

    url_series = df["url"].astype(str).str.strip().str.casefold()
    target_url = url_key.strip().casefold()
    mask = url_series == target_url

    if not mask.any():
        missing_row = {column: None for column in df.columns}
        missing_row["url"] = url_key
        df = pd.concat([df, pd.DataFrame([missing_row])], ignore_index=True)
        url_series = df["url"].astype(str).str.strip().str.casefold()
        mask = url_series == target_url

    updates: dict[str, Any] = {}
    if manual_min is not None:
        updates["manual_carsales_min"] = manual_min
    if manual_max is not None:
        updates["manual_carsales_max"] = manual_max
    if sold_last_30d is not None:
        updates["manual_carsales_sold_30d"] = sold_last_30d
        updates["manual_recent_sales_30d"] = sold_last_30d
    if skipped is not None:
        updates["carsales_skipped"] = bool(skipped)

    if not updates:
        return False

    for column, value in updates.items():
        if column not in df.columns:
            df[column] = None
        df.loc[mask, column] = value

    if "manual_carsales_avg" in df.columns:
        df.loc[mask, "manual_carsales_avg"] = df.loc[mask].apply(
            lambda row: _manual_avg_from_values(
                row.get("manual_carsales_min"), row.get("manual_carsales_max")
            ),
            axis=1,
        )

    _atomic_write(df, path)
    return True


def update_vehicle_estimates(
    url: str,
    manual_min: float | None = None,
    manual_max: float | None = None,
    sold_last_30d: int | None = None,
    *,
    skipped: bool | None = None,
) -> bool:
    """
    Update manual Carsales estimates for a vehicle identified by URL.

    Writes to active_vehicle_details.csv (when present) using an atomic write to
    avoid corruption.
    """
    updates: dict[str, Any] = {}
    if manual_min is not None:
        updates["manual_carsales_min"] = manual_min
    if manual_max is not None:
        updates["manual_carsales_max"] = manual_max
    if sold_last_30d is not None:
        updates["manual_carsales_sold_30d"] = sold_last_30d
        updates["manual_recent_sales_30d"] = sold_last_30d
    if skipped is not None:
        updates["carsales_skipped"] = bool(skipped)

    if not updates:
        return False

    active_path = dataset_path("active_vehicle_details.csv")
    changed = _apply_updates_to_file(active_path, url, updates)
    _update_ai_manual_cache(url, manual_min, manual_max, sold_last_30d, skipped)
    if changed:
        upload_remote_data_bundle(["active_vehicle_details.csv"])
    return changed
