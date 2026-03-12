"""Split scraped listings into active, sold, and referred CSV snapshots."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd
from dateutil import parser as date_parser

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import dataset_path
    from shared.sold_cleaning import normalize_listing_fields
    from shared.canonical_tagging import tag_dataframe
    from shared.state_machine import ListingObservation, ensure_state_schema, upsert_state_row
    from shared.validators import R, validate_sold_cars_df
    from scripts.build_restricted_datasets import build_restricted_datasets
else:
    from shared.data_loader import dataset_path
    from shared.sold_cleaning import normalize_listing_fields
    from shared.canonical_tagging import tag_dataframe
    from shared.state_machine import ListingObservation, ensure_state_schema, upsert_state_row
    from shared.validators import R, validate_sold_cars_df
    from scripts.build_restricted_datasets import build_restricted_datasets
SOLD_FILE = dataset_path("sold_cars.csv")
REFERRED_FILE = dataset_path("referred_cars.csv")
ACTIVE_FILE = dataset_path("active_vehicle_details.csv")
STATIC_FILE = dataset_path("vehicle_static_details.csv")
SNAPSHOT_FILE = dataset_path("active_snapshots.csv")
STATE_FILE = dataset_path("vehicle_state.csv")
SOLD_DISCARD_LOG = dataset_path("scrapers/sold_discard_log.csv")

DEDUP_KEYS: Sequence[str] = ("url", "vin")
REFERRED_STATUSES = {"referred", "canceled", "cancelled", "closed"}
EXCLUDED_VARIANT_KEYWORDS = ("motorcycle",)
SOLD_REDUNDANT_COLUMNS = ("time_remaining_or_date_sold", "final_price", "final_bids", "status")
WOVR_PATTERN = re.compile(
    r"\bwovr\b|wovr[-\s]*(?:inspected|repairable|statutory)|write[-\s]?off",
    re.IGNORECASE,
)
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
YEAR_URL_PATTERN = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    return text.lower() in {"nan", "none", "n/a"}


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _parse_year(value: object) -> int | None:
    if _is_blank(value):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    try:
        year = int(text)
    except ValueError:
        try:
            year = int(float(text))
        except (TypeError, ValueError):
            return None
    current_year = datetime.now().year
    if 1950 <= year <= current_year + 1:
        return year
    return None


def _parse_price(value: object) -> int | None:
    if _is_blank(value):
        return None
    text = str(value).strip()
    cleaned = re.sub(r"[^\d.]", "", text)
    if not cleaned:
        return None
    try:
        price = int(float(cleaned))
    except ValueError:
        return None
    return price if price > 0 else None


def _parse_bids(value: object) -> int:
    parsed = _to_int(value)
    return parsed if parsed is not None and parsed >= 0 else 0


def _parse_date(value: object) -> str | None:
    if _is_blank(value):
        return None
    text = str(value).strip()
    try:
        parsed = date_parser.parse(text, fuzzy=True, dayfirst=True)
    except (ValueError, TypeError):
        return None
    return parsed.date().isoformat()


def _normalize_odometer(value: object) -> tuple[int | None, bool]:
    if _is_blank(value):
        return None, False
    parsed = _to_int(value)
    if parsed is None:
        return None, True
    if parsed == 0 or parsed < 1000 or parsed > 700000:
        return None, True
    return parsed, False


def _append_sold_discard_log(records: list[dict[str, object]]) -> None:
    if not records:
        return
    SOLD_DISCARD_LOG.parent.mkdir(parents=True, exist_ok=True)
    file_exists = SOLD_DISCARD_LOG.exists()
    df = pd.DataFrame(records)
    df.to_csv(SOLD_DISCARD_LOG, mode="a", header=not file_exists, index=False)


def _clean_sold_rows(
    frame: pd.DataFrame,
    *,
    static_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    if frame.empty:
        return frame, []
    static_lookup = {}
    if static_df is not None and not static_df.empty and "url" in static_df.columns:
        static_vin = static_df[["url", "vin"]].copy()
        static_vin["url"] = static_vin["url"].astype(str).str.strip()
        static_vin["vin"] = static_vin["vin"].astype(str).str.strip().str.upper()
        static_lookup = static_vin.set_index("url")["vin"].to_dict()
    cleaned_rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    timestamp = datetime.utcnow().isoformat()
    for _, row in frame.iterrows():
        row_dict = row.to_dict()
        url = str(row_dict.get("url", "") or "").strip()
        make = str(row_dict.get("make", "") or "").strip()
        model = str(row_dict.get("model", "") or "").strip()
        raw_year = row_dict.get("year")

        if not url:
            reason = R.NO_URL
        elif "sold-test" in url.lower() or str(raw_year).strip().lower() == "test":
            reason = R.TEST_ROW
        elif make.lower() == "test" and model.lower() == "test":
            reason = R.TEST_ROW
        else:
            reason = ""

        year = _parse_year(raw_year)
        if not reason and year is None:
            reason = R.BAD_YEAR

        raw_price = row_dict.get("price")
        if not reason and _is_blank(raw_price):
            reason = R.NO_PRICE
        price = _parse_price(raw_price)
        if not reason and price is None:
            reason = R.BAD_PRICE

        date_candidate = row_dict.get("date_sold")
        if _is_blank(date_candidate):
            date_candidate = row_dict.get("time_remaining_or_date_sold")
        if not reason and _is_blank(date_candidate):
            reason = R.NO_DATE_SOLD
        date_sold = _parse_date(date_candidate)
        if not reason and date_sold is None:
            reason = R.BAD_DATE_SOLD

        if reason:
            failures.append(
                {
                    "timestamp": timestamp,
                    "url": url,
                    "reason_code": reason,
                    "field_snapshot": json.dumps(
                        {
                            "year": raw_year,
                            "make": make,
                            "model": model,
                            "price": raw_price,
                            "date_sold": date_candidate,
                        },
                        ensure_ascii=True,
                    ),
                }
            )
            continue

        bids = _parse_bids(row_dict.get("bids"))
        odometer, odo_suspect = _normalize_odometer(row_dict.get("odometer_reading"))
        vin = str(row_dict.get("vin", "") or "").strip().upper()
        if (not vin or vin.lower() in {"nan", "none"}) and url in static_lookup:
            fallback = static_lookup.get(url, "")
            if fallback and fallback.lower() not in {"nan", "none"}:
                vin = fallback
                row_dict["vin"] = vin
        if vin and not VIN_RE.match(vin):
            failures.append(
                {
                    "timestamp": timestamp,
                    "url": url,
                    "reason_code": R.BAD_VIN,
                    "field_snapshot": json.dumps(
                        {"vin": vin, "make": make, "model": model},
                        ensure_ascii=True,
                    ),
                }
            )
            continue

        row_dict["year"] = year
        row_dict["price"] = price
        row_dict["bids"] = bids
        row_dict["date_sold"] = date_sold
        row_dict["odometer_reading"] = odometer if odometer is not None else ""
        row_dict["odo_suspect"] = int(odo_suspect)
        cleaned_rows.append(row_dict)

    cleaned_df = pd.DataFrame(cleaned_rows)
    return cleaned_df, failures


def _parse_year_from_url(url: str) -> int | None:
    if not url:
        return None
    match = YEAR_URL_PATTERN.search(str(url))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _build_snapshot_sold_candidates(snapshot_path: Path, static_path: Path) -> pd.DataFrame:
    if not snapshot_path.exists():
        return pd.DataFrame()
    snapshots = _load_dataframe(snapshot_path)
    if snapshots.empty or "snapshot_ts" not in snapshots.columns or "url" not in snapshots.columns:
        return pd.DataFrame()

    snapshots["snapshot_ts"] = pd.to_datetime(snapshots["snapshot_ts"], errors="coerce")
    snapshots["url"] = snapshots["url"].astype(str).str.strip()
    snapshots = snapshots.dropna(subset=["snapshot_ts"])
    snapshots = snapshots[snapshots["url"] != ""]
    if snapshots.empty:
        return pd.DataFrame()

    snapshots["snapshot_date"] = snapshots["snapshot_ts"].dt.date
    dates = sorted(date for date in snapshots["snapshot_date"].unique() if date is not None)
    if len(dates) < 2:
        return pd.DataFrame()
    latest_date = max(dates)
    prev_date = max(date for date in dates if date < latest_date)

    prev_day = snapshots[snapshots["snapshot_date"] == prev_date].copy()
    latest_day = snapshots[snapshots["snapshot_date"] == latest_date].copy()
    missing_urls = set(prev_day["url"]) - set(latest_day["url"])
    if not missing_urls:
        return pd.DataFrame()

    prev_day = prev_day[prev_day["url"].isin(missing_urls)]
    prev_day = prev_day.sort_values("snapshot_ts")
    last_seen = prev_day.groupby("url", as_index=False).tail(1).copy()

    base = last_seen[["url", "price_numeric", "price_text", "bids_numeric"]].copy()
    base["price"] = base["price_numeric"]
    missing_price = base["price"].isna() | (base["price"] == 0)
    if "price_text" in base.columns and missing_price.any():
        base.loc[missing_price, "price"] = base.loc[missing_price, "price_text"].apply(_parse_price)
    if "bids_numeric" in base.columns:
        base["bids"] = base["bids_numeric"].fillna(0).astype(int)
    else:
        base["bids"] = 0
    base["date_sold"] = prev_date.isoformat()
    base["time_remaining_or_date_sold"] = base["date_sold"]
    base["status"] = "sold"

    static_df = _load_dataframe(static_path)
    if not static_df.empty and "url" in static_df.columns:
        static_df = static_df.copy()
        static_df["url"] = static_df["url"].astype(str).str.strip()
        static_df = static_df.drop_duplicates(subset=["url"], keep="last")
        merged = base.merge(static_df, on="url", how="left", suffixes=("", "_static"))
    else:
        merged = base

    if "year" not in merged.columns:
        merged["year"] = pd.NA
    missing_year = _blank_mask(merged["year"])
    if missing_year.any():
        merged.loc[missing_year, "year"] = merged.loc[missing_year, "url"].apply(_parse_year_from_url)

    return merged


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


def _prepare_sold_rows(frame: pd.DataFrame, *, static_df: pd.DataFrame | None = None) -> pd.DataFrame:
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
    cleaned, failures = _clean_sold_rows(prepared, static_df=static_df)
    _append_sold_discard_log(failures)
    drop_cols = [column for column in SOLD_REDUNDANT_COLUMNS if column in cleaned.columns]
    if drop_cols:
        cleaned = cleaned.drop(columns=drop_cols)
        print(f"Pruned redundant sold columns: {drop_cols}")
    if "sale_price" in cleaned.columns:
        cleaned = cleaned.drop(columns=["sale_price"])
    return cleaned


def _prepare_referred_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame()
    prepared = frame.copy()
    for col in ("price", "bids"):
        if col in prepared.columns:
            prepared[col] = pd.NA
    if "date_sold" in prepared.columns:
        prepared["date_sold"] = pd.NaT
    if "time_remaining_or_date_sold" in prepared.columns:
        prepared["time_remaining_or_date_sold"] = pd.NA
    if "referral_reason" not in prepared.columns:
        prepared["referral_reason"] = ""
    mask = _blank_mask(prepared["referral_reason"])
    if "general_condition" in prepared.columns:
        prepared.loc[mask, "referral_reason"] = prepared.loc[mask, "general_condition"]
        mask = _blank_mask(prepared["referral_reason"])
    prepared["referral_reason"] = prepared["referral_reason"].fillna("")
    return prepared


def _merge_preserving_history(
    path: Path,
    new_rows: pd.DataFrame,
    label: str,
    prepare_fn: Callable[..., pd.DataFrame] | None = None,
    ensure_schema: bool = False,
    validator: Callable[[pd.DataFrame], tuple[pd.DataFrame, dict[str, int]]] | None = None,
    *,
    prepare_kwargs: dict[str, object] | None = None,
) -> None:
    existing_raw = _load_dataframe(path)
    prepare_kwargs = prepare_kwargs or {}
    prepared_existing = prepare_fn(existing_raw, **prepare_kwargs) if prepare_fn else existing_raw
    prepared_new = prepare_fn(new_rows, **prepare_kwargs) if prepare_fn else new_rows

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

    if validator is not None:
        combined, stats = validator(combined)
        if stats["rows_dropped"]:
            print(f"{label.title()} validator dropped {stats['rows_dropped']} row(s) before write.")

    _atomic_write(combined, path)
    print(f"{label.title()} listings saved to {path} (total {len(combined)}, +{added}).")
    if label == "sold":
        print(f"[INFO] sold_added={added}")


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


def _remove_wovr_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    columns = [col for col in ("variant", "url") if col in frame.columns]
    if not columns:
        return frame
    combined = frame[columns].fillna("").astype(str).agg(" ".join, axis=1)
    mask = combined.str.contains(WOVR_PATTERN, na=False)
    removed = int(mask.sum())
    if removed:
        frame = frame.loc[~mask].copy()
        print(f"Filtered out {removed} WOVR listing(s) from active listings.")
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

    dynamic_columns = {"status", "time_remaining_or_date_sold", "price", "bids", "date_sold"}
    enriched = active_target.copy()
    enriched["_url_norm"] = _normalize_url(enriched["url"])
    existing = existing_active.copy()
    existing["_url_norm"] = _normalize_url(existing["url"])
    lookup = existing.set_index("_url_norm")

    for column in lookup.columns:
        if column in ("_url_norm",):
            continue
        if column not in dynamic_columns:
            continue
        if column not in enriched.columns:
            enriched[column] = pd.NA
        right_values = enriched["_url_norm"].map(lookup[column])
        blank_mask = _blank_mask(enriched[column])
        enriched.loc[blank_mask, column] = right_values[blank_mask]

    enriched.drop(columns=["_url_norm"], inplace=True)
    return enriched


def _load_state_table() -> pd.DataFrame:
    if not STATE_FILE.exists():
        return ensure_state_schema(pd.DataFrame())
    try:
        state_df = pd.read_csv(STATE_FILE, low_memory=False)
    except Exception:
        state_df = pd.DataFrame()
    return ensure_state_schema(state_df)


def _to_state_observation(
    row: pd.Series,
    *,
    run_id: str,
    observed_at: str,
    target_state: str,
    evidence: str,
) -> ListingObservation:
    url = str(row.get("url", "") or "").strip()
    price = row.get("price", "")
    bids = row.get("bids", "")
    time_remaining = row.get("time_remaining_or_date_sold", "")
    return ListingObservation(
        url=url,
        observed_at=observed_at,
        run_id=run_id,
        is_live=(target_state == "active"),
        has_sale_price=(target_state == "sold"),
        is_referred=(target_state == "referred"),
        fetch_failed=False,
        current_price=price if pd.notna(price) else "",
        bid_count=bids if pd.notna(bids) else "",
        time_remaining=time_remaining if pd.notna(time_remaining) else "",
        evidence=evidence,
        fetch_error="",
    )


def _sync_state_from_views(
    active_df: pd.DataFrame,
    sold_df: pd.DataFrame,
    referred_df: pd.DataFrame,
    *,
    run_id: str,
) -> pd.DataFrame:
    state_df = _load_state_table()
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for _, row in active_df.iterrows():
        obs = _to_state_observation(
            row,
            run_id=run_id,
            observed_at=observed_at,
            target_state="active",
            evidence="update_master_active_view",
        )
        if not obs.url:
            continue
        state_df, _ = upsert_state_row(state_df, obs)

    for _, row in sold_df.iterrows():
        obs = _to_state_observation(
            row,
            run_id=run_id,
            observed_at=observed_at,
            target_state="sold",
            evidence="update_master_sold_view",
        )
        if not obs.url:
            continue
        state_df, _ = upsert_state_row(state_df, obs)

    for _, row in referred_df.iterrows():
        obs = _to_state_observation(
            row,
            run_id=run_id,
            observed_at=observed_at,
            target_state="referred",
            evidence="update_master_referred_view",
        )
        if not obs.url:
            continue
        state_df, _ = upsert_state_row(state_df, obs)

    _atomic_write(ensure_state_schema(state_df), STATE_FILE)
    print(f"Listing state saved to {STATE_FILE} ({len(state_df)} rows).")
    return state_df


def _prune_urls_from_dataset(path: Path, urls: set[str], label: str) -> None:
    if not urls or not path.exists():
        return
    existing = _load_dataframe(path)
    if existing.empty or "url" not in existing.columns:
        return
    existing["_url_norm"] = _normalize_url(existing["url"])
    norm_urls = {_normalize_url(pd.Series([url])).iloc[0] for url in urls if url}
    mask = existing["_url_norm"].isin(norm_urls)
    removed = int(mask.sum())
    if removed:
        existing = existing.loc[~mask].copy()
        existing.drop(columns=["_url_norm"], inplace=True)
        _atomic_write(existing, path)
        print(f"Removed {removed} {label} listing(s) now marked as referred.")


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
    run_id = datetime.now(timezone.utc).strftime("master_%Y%m%dT%H%M%SZ")
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
    valid_statuses = {"active", "sold", "referred", "canceled", "cancelled", "closed"}
    df.loc[~df["status"].isin(valid_statuses), "status"] = "active"

    for column in optional_dynamic_columns:
        if column in df.columns and df[column].dtype == object:
            df[column] = df[column].replace({"": pd.NA, "nan": pd.NA})

    sold_df = df[df["status"] == "sold"].copy()
    referred_df = df[df["status"].isin(REFERRED_STATUSES)].copy()
    active_df = df[df["status"] == "active"].copy()
    # Snapshot-missing listings are not treated as sold. We only transition to sold/referred
    # when a listing is explicitly scraped with a terminal status.
    snapshot_sold_df = pd.DataFrame()
    if SNAPSHOT_FILE.exists():
        snapshots = _load_dataframe(SNAPSHOT_FILE)
        if not snapshots.empty and "snapshot_ts" in snapshots.columns and "url" in snapshots.columns:
            snapshots["snapshot_ts"] = pd.to_datetime(snapshots["snapshot_ts"], errors="coerce")
            snapshots = snapshots.dropna(subset=["snapshot_ts"])
            if not snapshots.empty:
                snapshots["snapshot_date"] = snapshots["snapshot_ts"].dt.date
                dates = sorted(date for date in snapshots["snapshot_date"].unique() if date is not None)
                if len(dates) >= 2:
                    latest_date = max(dates)
                    prev_date = max(date for date in dates if date < latest_date)
                    prev_day = snapshots[snapshots["snapshot_date"] == prev_date]
                    latest_day = snapshots[snapshots["snapshot_date"] == latest_date]
                    missing_urls = set(prev_day["url"].astype(str)) - set(latest_day["url"].astype(str))
                    if missing_urls:
                        print(
                            f"[INFO] snapshot-missing URLs detected (no status change): {len(missing_urls)}"
                        )
                        snapshot_sold_df = _build_snapshot_sold_candidates(SNAPSHOT_FILE, STATIC_FILE)

    if not snapshot_sold_df.empty:
        sold_df = pd.concat([sold_df, snapshot_sold_df], ignore_index=True, sort=False)
        if "url" in sold_df.columns:
            sold_df = sold_df.drop_duplicates(subset=["url"], keep="last")
        print(f"[INFO] Added {len(snapshot_sold_df)} snapshot-missing listing(s) to sold candidates.")
    active_df = _remove_wovr_rows(active_df)
    existing_active = _load_dataframe(ACTIVE_FILE)

    if not sold_df.empty:
        sold_df = tag_dataframe(
            sold_df,
            source="grays_sold",
            require_price=True,
            filter_unclassified=False,
            append_log=True,
        )
    if not active_df.empty:
        active_df = tag_dataframe(
            active_df,
            source="grays_active",
            require_price=False,
            filter_unclassified=False,
            append_log=True,
        )

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
    referred_urls: set[str] = set()
    if "url" in referred_df.columns and not referred_df.empty:
        referred_urls = {url.strip() for url in referred_df["url"].dropna().tolist() if str(url).strip()}
    existing_referred = _load_dataframe(REFERRED_FILE)
    if not existing_referred.empty and "url" in existing_referred.columns:
        referred_urls.update(
            {url.strip() for url in existing_referred["url"].dropna().tolist() if str(url).strip()}
        )
    # Do not purge sold based on referred URLs; sold history is authoritative.

    static_df = _load_dataframe(STATIC_FILE)
    _merge_preserving_history(
        SOLD_FILE,
        sold_df,
        "sold",
        prepare_fn=_prepare_sold_rows,
        ensure_schema=True,
        validator=validate_sold_cars_df,
        prepare_kwargs={"static_df": static_df},
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
    if "status" in active_target.columns:
        active_target["status"] = active_target["status"].fillna("active").astype(str).str.strip().str.lower()
        active_target = active_target[active_target["status"] == "active"].copy()
        active_target["status"] = "active"
    if "drivetrain_source" in active_target.columns:
        active_target = active_target.drop(columns=["drivetrain_source"])
    _atomic_write(active_target, ACTIVE_FILE)
    print(f"Active listings saved to {ACTIVE_FILE} ({len(active_target)} rows).")
    _sync_state_from_views(active_target, sold_df, referred_df, run_id=run_id)

    completed_urls: set[str] = set()
    if "url" in sold_df.columns:
        completed_urls.update(sold_df["url"].dropna().tolist())
    if "url" in referred_df.columns:
        completed_urls.update(referred_df["url"].dropna().tolist())
    _prune_urls_from_dataset(dataset_path("active_vehicle_links.csv"), completed_urls, "active links (sold/referred)")
    if "url" in active_target.columns:
        active_urls = {url.strip() for url in active_target["url"].dropna().tolist() if str(url).strip()}
        if active_urls:
            _prune_urls_from_dataset(SOLD_FILE, active_urls, "sold (now active)")
    # Static identity is durable; lifecycle changes are tracked in vehicle_state.csv.
    try:
        build_restricted_datasets()
    except Exception as exc:
        print(f"Restricted dataset build failed: {exc}")


if __name__ == "__main__":
    update_master_database()
