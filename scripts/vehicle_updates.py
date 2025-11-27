from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from shared.data_loader import dataset_path


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
    if "manual_instant_offer_estimate" not in df.columns:
        df["manual_instant_offer_estimate"] = None
    if "carsales_skipped" not in df.columns:
        df["carsales_skipped"] = False
    return df


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

    _atomic_write(df, path)
    return True


def update_vehicle_estimates(
    url: str,
    manual_min: float | None = None,
    manual_instant_offer: float | None = None,
    *,
    skipped: bool | None = None,
) -> bool:
    """
    Update manual Carsales estimates for a vehicle identified by URL.

    Writes to vehicle_static_details.csv and active_vehicle_details.csv (when present)
    using an atomic write to avoid corruption.
    """
    updates: dict[str, Any] = {}
    if manual_min is not None:
        updates["manual_carsales_min"] = manual_min
    if manual_instant_offer is not None:
        updates["manual_instant_offer_estimate"] = manual_instant_offer
    if skipped is not None:
        updates["carsales_skipped"] = bool(skipped)

    if not updates:
        return False

    targets = [
        dataset_path("vehicle_static_details.csv"),
        dataset_path("active_vehicle_details.csv"),
    ]
    changed = False
    for target in targets:
        changed = _apply_updates_to_file(target, url, updates) or changed
    return changed
