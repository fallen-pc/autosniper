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
    from shared.sold_cleaning import normalize_listing_fields
    from scripts.build_restricted_datasets import build_restricted_datasets
else:
    from shared.data_loader import DATA_DIR
    from shared.sold_cleaning import normalize_listing_fields
    from scripts.build_restricted_datasets import build_restricted_datasets
SOLD_FILE = DATA_DIR / "sold_cars.csv"
REFERRED_FILE = DATA_DIR / "referred_cars.csv"
ACTIVE_FILE = DATA_DIR / "active_vehicle_details.csv"
STATIC_FILE = DATA_DIR / "vehicle_static_details.csv"

DEDUP_KEYS: Sequence[str] = ("url", "vin")
REFERRED_STATUSES = {"referred", "canceled", "cancelled", "closed"}
EXCLUDED_VARIANT_KEYWORDS = ("motorcycle",)
SOLD_REDUNDANT_COLUMNS = ("time_remaining_or_date_sold", "final_price", "final_bids", "status")
MANUAL_CARSALES_COLUMNS = (
    "manual_carsales_min",
    "manual_carsales_max",
    "manual_carsales_avg",
    "manual_carsales_sold_30d",
    "manual_recent_sales_30d",
    "manual_carsales_count",
    "manual_carsales_table",
    "manual_carsales_estimate",
    "carsales_skipped",
)


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
    if "price" not in prepared.columns:
        prepared["price"] = ""
    mask = _blank_mask(prepared["price"])
    for column in ("final_price", "final_price_numeric", "sale_price"):
        if column in prepared.columns:
            prepared.loc[mask, "price"] = prepared.loc[mask, column]
            mask = _blank_mask(prepared["price"])
            if not mask.any():
                break
    prepared["price"] = prepared["price"].fillna("")
    drop_cols = [column for column in SOLD_REDUNDANT_COLUMNS if column in prepared.columns]
    if drop_cols:
        prepared = prepared.drop(columns=drop_cols)
        print(f"Pruned redundant sold columns: {drop_cols}")
    manual_cols = [column for column in MANUAL_CARSALES_COLUMNS if column in prepared.columns]
    if manual_cols:
        prepared = prepared.drop(columns=manual_cols)
    if "sale_price" in prepared.columns:
        prepared = prepared.drop(columns=["sale_price"])
    return prepared


def _prepare_referred_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame()
    prepared = frame.copy()
    if "referral_reason" not in prepared.columns:
        prepared["referral_reason"] = ""
    mask = _blank_mask(prepared["referral_reason"])
    if "general_condition" in prepared.columns:
        prepared.loc[mask, "referral_reason"] = prepared.loc[mask, "general_condition"]
        mask = _blank_mask(prepared["referral_reason"])
    prepared["referral_reason"] = prepared["referral_reason"].fillna("")
    manual_cols = [column for column in MANUAL_CARSALES_COLUMNS if column in prepared.columns]
    if manual_cols:
        prepared = prepared.drop(columns=manual_cols)
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


def _remove_excluded_variants(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "variant" not in frame.columns:
        return frame
    variant_series = frame["variant"].astype(str)
    mask = variant_series.str.contains("|".join(EXCLUDED_VARIANT_KEYWORDS), case=False, na=False)
    removed = int(mask.sum())
    if removed:
        frame = frame.loc[~mask].copy()
        print(f"Filtered out {removed} listing(s) based on variant keywords: {EXCLUDED_VARIANT_KEYWORDS}.")
    return frame


def _project_columns(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame(columns=columns)
    return frame.reindex(columns=columns)


def _normalize_url(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.casefold()


def _restore_active_columns(active_target: pd.DataFrame, existing_active: pd.DataFrame) -> pd.DataFrame:
    """Bring forward dynamic auction columns (price/bids/time/status) from the existing active snapshot."""
    if active_target.empty:
        return active_target
    if existing_active.empty or "url" not in active_target.columns or "url" not in existing_active.columns:
        return active_target

    enriched = active_target.copy()
    enriched["_url_norm"] = _normalize_url(enriched["url"])
    existing = existing_active.copy()
    existing["_url_norm"] = _normalize_url(existing["url"])
    lookup = existing.set_index("_url_norm")

    for column in lookup.columns:
        if column in ("_url_norm",):
            continue
        if column not in enriched.columns:
            enriched[column] = pd.NA
        right_values = enriched["_url_norm"].map(lookup[column])
        blank_mask = _blank_mask(enriched[column])
        enriched.loc[blank_mask, column] = right_values[blank_mask]

    enriched.drop(columns=["_url_norm"], inplace=True)
    return enriched


def _prune_static_dataset(urls_to_remove: set[str]) -> None:
    """Drop completed listings (sold/referred) from the static vehicle dataset."""
    if not urls_to_remove:
        return
    static_df = _load_dataframe(STATIC_FILE)
    if static_df.empty or "url" not in static_df.columns:
        return
    mask = static_df["url"].isin(urls_to_remove)
    removed = int(mask.sum())
    if not removed:
        return
    pruned = static_df.loc[~mask].copy()
    _atomic_write(pruned, STATIC_FILE)
    print(f"Pruned {removed} completed listing(s) from {STATIC_FILE.name}.")


def update_master_database() -> None:
    df = _load_dataframe(ACTIVE_FILE)
    if df.empty:
        print("No active listings available; ensure you've promoted the latest scrape into active listings.")
        return
    if "status" not in df.columns:
        df["status"] = "active"

    df = normalize_listing_fields(df)
    optional_dynamic_columns = ("time_remaining_or_date_sold", "price", "bids")
    for column in optional_dynamic_columns:
        if column not in df.columns:
            df[column] = pd.NA

    df = _remove_excluded_variants(df)
    df["status"] = df["status"].astype(str).str.strip().str.lower()

    for column in optional_dynamic_columns:
        if column in df.columns and df[column].dtype == object:
            df[column] = df[column].replace({"": pd.NA, "nan": pd.NA})

    sold_df = df[df["status"] == "sold"].copy()
    referred_df = df[df["status"].isin(REFERRED_STATUSES)].copy()
    active_df = df[df["status"] == "active"].copy()
    existing_active = _load_dataframe(ACTIVE_FILE)

    if not sold_df.empty:
        prepared_snapshot = _prepare_sold_rows(sold_df)
        sale_series = prepared_snapshot["price"] if "price" in prepared_snapshot.columns else pd.Series(
            dtype=object, index=prepared_snapshot.index
        )
        blank_sale_mask = _blank_mask(sale_series)
        if blank_sale_mask.any():
            moved_rows = sold_df.loc[blank_sale_mask].copy()
            if not moved_rows.empty:
                moved_rows["status"] = "referred"
                referred_df = pd.concat([referred_df, moved_rows], ignore_index=True, sort=False)
                sold_df = sold_df.loc[~blank_sale_mask].copy()
                print(f"Moved {len(moved_rows)} sold listing(s) without sale price into referred dataset.")

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
    active_target = _restore_active_columns(active_target, existing_active)
    _atomic_write(active_target, ACTIVE_FILE)
    print(f"Active listings saved to {ACTIVE_FILE} ({len(active_target)} rows).")
    completed_urls: set[str] = set()
    if "url" in sold_df.columns:
        completed_urls.update(sold_df["url"].dropna().tolist())
    if "url" in referred_df.columns:
        completed_urls.update(referred_df["url"].dropna().tolist())
    _prune_static_dataset({url.strip() for url in completed_urls if url})
    try:
        build_restricted_datasets()
    except Exception as exc:
        print(f"Restricted dataset build failed: {exc}")


if __name__ == "__main__":
    update_master_database()
