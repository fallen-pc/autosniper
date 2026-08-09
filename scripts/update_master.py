"""Split scraped listings into active, sold, and referred CSV snapshots."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd
from dateutil import parser as date_parser

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import append_dataframe_csv_atomic, write_dataframe_csv_atomic
    from shared.csv_utils import CSV_READ_ERRORS
    from shared.data_loader import dataset_path
    from shared.governance import SOLD_DETAIL_SCHEMA
    from shared.sold_cleaning import normalize_listing_fields
    from shared.canonical_tagging import tag_dataframe
    from shared.schema import TERMINAL_STATES
    from shared.state_machine import ensure_state_schema, normalize_state
    from shared.validators import R, validate_sold_cars_df
    from shared.exclusions import append_pipeline_exclusions
    from scripts.build_restricted_datasets import build_restricted_datasets
else:
    from scripts.atomic_csv import append_dataframe_csv_atomic, write_dataframe_csv_atomic
    from shared.csv_utils import CSV_READ_ERRORS
    from shared.data_loader import dataset_path
    from shared.governance import SOLD_DETAIL_SCHEMA
    from shared.sold_cleaning import normalize_listing_fields
    from shared.canonical_tagging import tag_dataframe
    from shared.schema import TERMINAL_STATES
    from shared.state_machine import ensure_state_schema, normalize_state
    from shared.validators import R, validate_sold_cars_df
    from shared.exclusions import append_pipeline_exclusions
    from scripts.build_restricted_datasets import build_restricted_datasets

logger = logging.getLogger(__name__)

SOLD_FILE = dataset_path("sold_cars.csv")
REFERRED_FILE = dataset_path("referred_cars.csv")
ACTIVE_FILE = dataset_path("active_vehicle_details.csv")
STATIC_FILE = dataset_path("vehicle_static_details.csv")
STATE_FILE = dataset_path("vehicle_state.csv")
SOLD_DISCARD_LOG = dataset_path("scrapers/sold_discard_log.csv")
NORMALIZED_FILE = dataset_path("normalised_data.csv")

DEDUP_KEYS: Sequence[str] = ("url", "vin")
REFERRED_STATUSES = {"referred", "canceled", "cancelled", "closed"}
EXCLUDED_VARIANT_KEYWORDS = ("motorcycle",)
SOLD_REDUNDANT_COLUMNS = ("time_remaining_or_date_sold", "final_price", "final_bids", "status")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WOVR_PATTERN = re.compile(
    r"\bwovr\b|wovr[-\s]*(?:inspected|repairable|statutory)|write[-\s]?off",
    re.IGNORECASE,
)
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
AU_TZINFOS = {
    "AEDT": 11 * 3600,
    "AEST": 10 * 3600,
    "ACDT": 10 * 3600 + 1800,
    "ACST": 9 * 3600 + 1800,
    "AWST": 8 * 3600,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


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
    if ISO_DATE_RE.match(text):
        try:
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    try:
        parsed = date_parser.parse(text, fuzzy=True, dayfirst=True, tzinfos=AU_TZINFOS)
    except (ValueError, TypeError):
        return None
    return parsed.date().isoformat()


def _normalize_odometer(value: object) -> tuple[int | None, bool]:
    if _is_blank(value):
        return None, False
    parsed = _to_int(value)
    suspect = False
    if parsed is None:
        text = str(value)
        suspect = True
        match = re.search(r"\d[\d, ]*", text)
        if match:
            parsed = _to_int(match.group(0))
    if parsed is None:
        return None, True
    if parsed == 0 or parsed < 1000 or parsed > 700000:
        return None, True
    if re.search(r"discrepanc|suspect|unknown|not verified", str(value), re.IGNORECASE):
        suspect = True
    return parsed, suspect


def _append_sold_discard_log(records: list[dict[str, object]]) -> None:
    if not records:
        return
    SOLD_DISCARD_LOG.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)
    append_dataframe_csv_atomic(df, SOLD_DISCARD_LOG, index=False)
    append_pipeline_exclusions(records, stage="sold_clean")


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
    timestamp = _utc_now_iso()
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


def _load_dataframe(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False) if path.exists() else pd.DataFrame()


def _atomic_write(df: pd.DataFrame, path: Path) -> None:
    write_dataframe_csv_atomic(df, path, index=False)


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
    prepared["price"] = prepared["price"].where(prepared["price"].notna(), "")
    cleaned, failures = _clean_sold_rows(prepared, static_df=static_df)
    _append_sold_discard_log(failures)
    drop_cols = [column for column in SOLD_REDUNDANT_COLUMNS if column in cleaned.columns]
    if drop_cols:
        cleaned = cleaned.drop(columns=drop_cols)
        print(f"Pruned redundant sold columns: {drop_cols}")
    if "sale_price" in cleaned.columns:
        cleaned = cleaned.drop(columns=["sale_price"])
    for column in SOLD_DETAIL_SCHEMA:
        if column not in cleaned.columns:
            cleaned[column] = ""
    return cleaned.reindex(columns=SOLD_DETAIL_SCHEMA)


def _sold_rows_missing_sale_price(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=bool, index=getattr(frame, "index", None))
    working = frame.copy()
    if "price" not in working.columns:
        working["price"] = ""
    mask = _blank_mask(working["price"])
    for column in ("final_price", "final_price_numeric", "sale_price"):
        if column in working.columns:
            fill_mask = mask & ~_blank_mask(working[column])
            if fill_mask.any():
                working.loc[fill_mask, "price"] = working.loc[fill_mask, column]
            mask = _blank_mask(working["price"])
            if not mask.any():
                break
    return mask.reindex(frame.index, fill_value=False)


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
    dedup_keys: Sequence[str] = DEDUP_KEYS,
    dedup_existing: bool = False,
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
        except (TypeError, ValueError):
            schema_changed = True

    if prepared_new.empty:
        if dedup_existing:
            dedup_cols = [
                col for col in dedup_keys if col in prepared_existing.columns
            ]
            if dedup_cols:
                before = len(prepared_existing)
                prepared_existing = prepared_existing.drop_duplicates(subset=dedup_cols, keep="first").copy()
                schema_changed |= len(prepared_existing) != before
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
            col for col in dedup_keys if col in prepared_existing.columns and col in prepared_new.columns
        ]
        if dedup_existing and dedup_cols:
            prepared_existing = prepared_existing.drop_duplicates(subset=dedup_cols, keep="first").copy()
        filtered_new = prepared_new.copy()
        if dedup_cols:
            existing_keys = set(_build_key(prepared_existing, dedup_cols))
            new_keys = _build_key(filtered_new, dedup_cols)
            mask_existing = new_keys.isin(existing_keys) & new_keys.ne("")
            filtered_new = filtered_new[~mask_existing].copy()
            filtered_new = filtered_new.drop_duplicates(subset=dedup_cols, keep="first")
        if filtered_new.empty:
            combined = prepared_existing.copy()
            added = 0
        else:
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


def _filter_active_rows_with_live_signals(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    working = frame.copy()
    if "price" not in working.columns:
        working["price"] = ""
    if "time_remaining_or_date_sold" not in working.columns:
        working["time_remaining_or_date_sold"] = ""
    keep_mask = (~_blank_mask(working["price"])) | (~_blank_mask(working["time_remaining_or_date_sold"]))
    removed = int((~keep_mask).sum())
    if removed:
        print(f"Filtered out {removed} active row(s) without price or countdown evidence.")
    return working.loc[keep_mask].copy()


def _project_columns(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame(columns=columns)
    return frame.reindex(columns=columns)


def _normalize_url(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.casefold()


def _load_active_queue_urls() -> set[str]:
    queue_path = dataset_path("active_vehicle_links.csv")
    if not queue_path.exists():
        return set()
    queue_df = _load_dataframe(queue_path)
    if queue_df.empty or "url" not in queue_df.columns:
        return set()
    return {
        url
        for url in _normalize_url(queue_df["url"]).tolist()
        if url
    }


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


STATE_DROP_COLUMNS = {
    "state",
    "current_price",
    "final_sale_price",
    "final_sale_date",
    "sale_price_source",
    "bid_count",
    "time_remaining",
    "last_seen_at",
    "terminal_reason",
    "state_updated_at",
    "fetch_fail_count",
    "last_fetch_error",
    "last_evidence",
    "run_id",
}


def _join_state_with_static(state_slice: pd.DataFrame, static_df: pd.DataFrame) -> pd.DataFrame:
    if state_slice.empty:
        return pd.DataFrame()
    working = state_slice.copy()
    if "url" in working.columns:
        working["url"] = working["url"].astype(str).str.strip()
        working["_url_norm"] = _normalize_url(working["url"])
    else:
        working["_url_norm"] = ""

    if static_df.empty or "url" not in static_df.columns:
        return working.drop(columns=["_url_norm"], errors="ignore")

    static_lookup = static_df.copy()
    static_lookup["url"] = static_lookup["url"].astype(str).str.strip()
    static_lookup["_url_norm"] = _normalize_url(static_lookup["url"])
    static_lookup = static_lookup.rename(columns={"url": "url_static"})
    merged = working.merge(static_lookup, on="_url_norm", how="left")
    if "url_static" in merged.columns:
        merged["url"] = merged["url_static"].fillna(merged.get("url", ""))
        merged.drop(columns=["url_static"], inplace=True)
    merged.drop(columns=["_url_norm"], inplace=True)
    return merged


def _derive_date_sold(row: pd.Series) -> str | None:
    candidate = _parse_date(row.get("time_remaining"))
    if candidate:
        return candidate
    candidate = _parse_date(row.get("last_seen_at"))
    return candidate


def _materialize_state_view(
    static_df: pd.DataFrame,
    state_df: pd.DataFrame,
    *,
    target_states: set[str],
    status_label: str,
    include_date_sold: bool = False,
) -> pd.DataFrame:
    if state_df.empty:
        return pd.DataFrame()
    slice_df = state_df[state_df["state"].isin(target_states)].copy()
    if slice_df.empty:
        return pd.DataFrame()
    merged = _join_state_with_static(slice_df, static_df)
    if merged.empty:
        return merged
    merged["status"] = status_label
    if status_label == "sold":
        if "current_price" in merged.columns:
            merged["last_observed_price"] = merged["current_price"]
        if "final_sale_price" in merged.columns:
            merged["price"] = merged["final_sale_price"]
        else:
            merged["price"] = ""
    elif "current_price" in merged.columns:
        merged["price"] = merged["current_price"]
    else:
        merged["price"] = ""
    if "bid_count" in merged.columns:
        merged["bids"] = merged["bid_count"]
    else:
        merged["bids"] = ""
    if "time_remaining" in merged.columns:
        merged["time_remaining_or_date_sold"] = merged["time_remaining"]
    else:
        merged["time_remaining_or_date_sold"] = ""
    if include_date_sold:
        if "final_sale_date" in merged.columns:
            final_sale_date = merged["final_sale_date"].where(~_blank_mask(merged["final_sale_date"]), None)
            derived_date = merged.apply(_derive_date_sold, axis=1)
            merged["date_sold"] = final_sale_date.fillna(derived_date)
        else:
            merged["date_sold"] = merged.apply(_derive_date_sold, axis=1)
    if status_label == "referred" and "terminal_reason" in merged.columns:
        merged["referral_reason"] = merged["terminal_reason"]
    drop_cols = [col for col in STATE_DROP_COLUMNS if col in merged.columns]
    if drop_cols:
        merged = merged.drop(columns=drop_cols)
    return merged


def _load_state_table() -> pd.DataFrame:
    if not STATE_FILE.exists():
        return ensure_state_schema(pd.DataFrame())
    try:
        state_df = pd.read_csv(STATE_FILE, low_memory=False)
    except CSV_READ_ERRORS as exc:
        logger.error(
            "Unreadable listing state %s (%s: %s); rebuilding state from an empty frame.",
            STATE_FILE,
            type(exc).__name__,
            exc,
        )
        state_df = pd.DataFrame()
    return ensure_state_schema(state_df)


def _load_static_identity_table() -> pd.DataFrame:
    static_df = _load_dataframe(STATIC_FILE)
    if NORMALIZED_FILE.parent != STATIC_FILE.parent:
        return static_df
    normalized_df = _load_dataframe(NORMALIZED_FILE)
    if normalized_df.empty:
        return static_df
    if static_df.empty:
        return normalized_df
    if "url" not in normalized_df.columns or "url" not in static_df.columns:
        return static_df
    combined = pd.concat([normalized_df, static_df], ignore_index=True, sort=False)
    combined["_url_norm"] = _normalize_url(combined["url"])
    combined = combined[combined["_url_norm"].ne("")]
    combined = combined.drop_duplicates(subset=["_url_norm"], keep="last")
    combined = combined.drop(columns=["_url_norm"])
    return combined.reset_index(drop=True)


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


def update_master_database() -> None:
    state_df = _load_state_table()
    if state_df.empty:
        print("vehicle_state.csv is empty; run update_bids first to populate listing states.")
        return
    state_df = state_df.copy()
    state_df["state"] = state_df["state"].apply(normalize_state)

    static_df = _load_static_identity_table()
    existing_active = _load_dataframe(ACTIVE_FILE)

    active_df = _materialize_state_view(
        static_df,
        state_df,
        target_states={"active"},
        status_label="active",
        include_date_sold=False,
    )
    sold_df = _materialize_state_view(
        static_df,
        state_df,
        target_states={"sold"},
        status_label="sold",
        include_date_sold=True,
    )
    referred_df = _materialize_state_view(
        static_df,
        state_df,
        target_states={"referred"},
        status_label="referred",
        include_date_sold=False,
    )
    withdrawn_df = _materialize_state_view(
        static_df,
        state_df,
        target_states={"withdrawn"},
        status_label="referred",
        include_date_sold=False,
    )
    if not withdrawn_df.empty:
        referred_df = pd.concat([referred_df, withdrawn_df], ignore_index=True, sort=False)

    for frame_name, frame in (("active", active_df), ("sold", sold_df), ("referred", referred_df)):
        if frame.empty:
            continue
        frame = normalize_listing_fields(frame)
        frame = _remove_excluded_variants(frame)
        frame["status"] = frame.get("status", frame_name).astype(str).str.strip().str.lower()
        if frame_name == "active":
            frame["status"] = "active"
        elif frame_name == "sold":
            frame["status"] = "sold"
        else:
            frame["status"] = "referred"
        if frame_name == "active":
            active_df = frame
        elif frame_name == "sold":
            sold_df = frame
        else:
            referred_df = frame

    if not active_df.empty:
        active_df = _remove_wovr_rows(active_df)
        active_df = _filter_active_rows_with_live_signals(active_df)
        active_queue_urls = _load_active_queue_urls()
        if active_queue_urls and "url" in active_df.columns:
            active_df["_url_norm"] = _normalize_url(active_df["url"])
            before_count = len(active_df)
            active_df = active_df[active_df["_url_norm"].isin(active_queue_urls)].copy()
            active_df.drop(columns=["_url_norm"], inplace=True)
            removed = before_count - len(active_df)
            if removed:
                print(f"Filtered out {removed} stale active state row(s) not present in active link queue.")

    for column in ("time_remaining_or_date_sold", "price", "bids", "date_sold"):
        if not active_df.empty and column not in active_df.columns:
            active_df[column] = pd.NA

    if not sold_df.empty:
        blank_sale_mask = _sold_rows_missing_sale_price(sold_df)
        if blank_sale_mask.any():
            skipped = int(blank_sale_mask.sum())
            sold_df = sold_df.loc[~blank_sale_mask].copy()
            print(
                f"Skipped {skipped} sold listing(s) without verified final sale price; "
                "only explicit Sold for evidence is materialized."
            )
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
        dedup_keys=("url",),
        dedup_existing=True,
    )

    if not active_df.empty:
        active_target = active_df.copy()
    else:
        if not existing_active.empty:
            seed_columns = list(existing_active.columns)
        elif not static_df.empty:
            seed_columns = list(static_df.columns) + [
                "status",
                "time_remaining_or_date_sold",
                "price",
                "bids",
                "date_sold",
            ]
        else:
            seed_columns = [
                "url",
                "status",
                "time_remaining_or_date_sold",
                "price",
                "bids",
                "date_sold",
            ]
        active_target = pd.DataFrame(columns=seed_columns)

    if "status" in active_target.columns:
        active_target["status"] = active_target["status"].fillna("active").astype(str).str.strip().str.lower()
        active_target = active_target[active_target["status"] == "active"].copy()
        active_target["status"] = "active"
    _atomic_write(active_target, ACTIVE_FILE)
    print(f"Active listings saved to {ACTIVE_FILE} ({len(active_target)} rows).")

    completed_urls: set[str] = set()
    if "url" in sold_df.columns:
        completed_urls.update(sold_df["url"].dropna().tolist())
    if "url" in referred_df.columns:
        completed_urls.update(referred_df["url"].dropna().tolist())
    if "url" in state_df.columns and "state" in state_df.columns:
        terminal_mask = state_df["state"].astype(str).str.strip().str.lower().isin(TERMINAL_STATES)
        terminal_urls = state_df.loc[terminal_mask, "url"].dropna().tolist()
        completed_urls.update(terminal_urls)
    _prune_urls_from_dataset(dataset_path("active_vehicle_links.csv"), completed_urls, "active links (terminal state)")
    if "url" in active_target.columns:
        active_urls = {url.strip() for url in active_target["url"].dropna().tolist() if str(url).strip()}
        if active_urls:
            existing_sold = _load_dataframe(SOLD_FILE)
            if not existing_sold.empty and "url" in existing_sold.columns:
                sold_urls = {url.strip() for url in existing_sold["url"].dropna().tolist() if str(url).strip()}
                overlaps = active_urls & sold_urls
                if overlaps:
                    print(
                        f"Preserved {len(overlaps)} sold-history row(s) whose URLs are currently active; "
                        "investigate lifecycle drift separately."
                    )
    # Static identity is durable; lifecycle changes are tracked in vehicle_state.csv.
    try:
        build_restricted_datasets()
    except Exception as exc:
        raise RuntimeError("Restricted dataset build failed after master update.") from exc


if __name__ == "__main__":
    update_master_database()
