"""Split scraped listings into active, sold, and referred CSV snapshots."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import DATA_DIR
else:
    from shared.data_loader import DATA_DIR

DETAILS_FILE = DATA_DIR / "vehicle_static_details.csv"
SOLD_FILE = DATA_DIR / "sold_cars.csv"
REFERRED_FILE = DATA_DIR / "referred_cars.csv"
ACTIVE_FILE = DATA_DIR / "active_vehicle_details.csv"

DEDUP_KEYS: Sequence[str] = ("url", "vin")
REFERRED_STATUSES = {"referred", "canceled", "cancelled", "closed"}


def _load_dataframe(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


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


def _build_key(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=str)

    keys = pd.Series([""] * len(frame), index=frame.index, dtype=object)
    for column in columns:
        if column not in frame.columns:
            continue
        part = (
            frame[column]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
            .replace("nan", "")
        )
        keys = keys.str.cat(part, sep="|")
    return keys.str.strip("|")


def _blank_mask(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool, index=series.index)
    text = series.astype(str).str.strip()
    return series.isna() | text.eq("") | text.str.lower().eq("nan")


def _prepare_sold_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame()
    prepared = frame.copy()
    if "sale_price" not in prepared.columns:
        prepared["sale_price"] = ""
    mask = _blank_mask(prepared["sale_price"])
    for column in ("final_price", "final_price_numeric", "price"):
        if column in prepared.columns:
            prepared.loc[mask, "sale_price"] = prepared.loc[mask, column]
            mask = _blank_mask(prepared["sale_price"])
            if not mask.any():
                break
    prepared["sale_price"] = prepared["sale_price"].fillna("")
    return prepared


def _prepare_referred_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame()
    prepared = frame.copy()
    if "referral_reason" not in prepared.columns:
        prepared["referral_reason"] = ""
    mask = _blank_mask(prepared["referral_reason"])
    for column in ("general_condition", "features_list"):
        if column in prepared.columns:
            prepared.loc[mask, "referral_reason"] = prepared.loc[mask, column]
            mask = _blank_mask(prepared["referral_reason"])
            if not mask.any():
                break
    prepared["referral_reason"] = prepared["referral_reason"].fillna("")
    return prepared


def _merge_preserving_history(
    path: Path,
    new_rows: pd.DataFrame,
    label: str,
    prepare_fn: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    ensure_schema: bool = False,
) -> None:
    existing_raw = _load_dataframe(path)
    prepared_existing = prepare_fn(existing_raw) if prepare_fn else existing_raw
    prepared_new = prepare_fn(new_rows) if prepare_fn else new_rows

    schema_changed = False
    if prepare_fn is not None:
        try:
            schema_changed = not prepared_existing.equals(existing_raw)
        except Exception:
            schema_changed = True

    if prepared_new.empty:
        if ensure_schema and schema_changed:
            _atomic_write(prepared_existing, path)
            print(f"{label.title()} listings saved to {path} (schema normalized; +0).")
        else:
            print(f"No {label} listings to add; {path.name} unchanged.")
        return

    if prepared_existing.empty:
        combined = prepared_new.copy()
        added = len(prepared_new)
    else:
        dedup_cols = [
            col for col in DEDUP_KEYS if col in prepared_existing.columns and col in prepared_new.columns
        ]
        filtered_new = prepared_new.copy()
        if dedup_cols:
            existing_keys = set(_build_key(prepared_existing, dedup_cols))
            new_keys = _build_key(filtered_new, dedup_cols)
            mask_existing = new_keys.isin(existing_keys) & new_keys.ne("")
            filtered_new = filtered_new[~mask_existing].copy()
            filtered_new = filtered_new.drop_duplicates(subset=dedup_cols, keep="first")
        combined = pd.concat([prepared_existing, filtered_new], ignore_index=True, sort=False)
        added = len(filtered_new)

    _atomic_write(combined, path)
    print(f"{label.title()} listings saved to {path} (total {len(combined)}, +{added}).")


def update_master_database() -> None:
    if not DETAILS_FILE.exists():
        print(f"Missing source file: {DETAILS_FILE}")
        return

    df = pd.read_csv(DETAILS_FILE)
    if df.empty:
        print(f"{DETAILS_FILE} is empty; nothing to process.")
        return

    df["status"] = df["status"].astype(str).str.strip().str.lower()

    sold_df = df[df["status"] == "sold"].copy()
    referred_df = df[df["status"].isin(REFERRED_STATUSES)].copy()
    active_df = df[df["status"] == "active"].copy()

    _merge_preserving_history(
        SOLD_FILE,
        sold_df,
        "sold",
        prepare_fn=_prepare_sold_rows,
        ensure_schema=True,
    )
    _merge_preserving_history(
        REFERRED_FILE,
        referred_df,
        "referred/canceled/closed",
        prepare_fn=_prepare_referred_rows,
        ensure_schema=True,
    )

    active_target = active_df if not active_df.empty else pd.DataFrame(columns=df.columns)
    _atomic_write(active_target, ACTIVE_FILE)
    print(f"Active listings saved to {ACTIVE_FILE} ({len(active_df)} rows).")

    # Keep vehicle_static_details.csv scoped to active inventory for the front-end.
    _atomic_write(active_target, DETAILS_FILE)
    print(f"{DETAILS_FILE} refreshed with {len(active_df)} active listings.")


if __name__ == "__main__":
    update_master_database()
