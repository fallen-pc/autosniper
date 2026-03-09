"""Utilities for ensuring the CSV datasets are present locally.

This module allows the app to pull a ZIP bundle of CSV files from a remote
location defined by environment variables. It keeps the repository light while
still supporting live data in hosted environments such as Streamlit Cloud.

Environment variables:
----------------------
AUTOSNIPER_DATA_URL
    Optional. If set, should point to a ZIP archive containing the CSV files.
    The archive may have files at the root level or inside a `CSV_data/`
    directory. The archive will be downloaded and extracted into `CSV_data/`.

AUTOSNIPER_DATA_TOKEN
    Optional bearer token that will be sent as `Authorization: Bearer <token>`
    when fetching the ZIP archive.

AUTOSNIPER_DATA_CACHE_MINUTES
    Optional integer (default: 30). Controls how frequently the remote bundle
    is re-downloaded. While the cache is "warm", extraction is skipped unless
    files are missing.
AUTOSNIPER_DATA_UPLOAD_URL
    Optional. If set, points to a writable endpoint (e.g., S3 presigned PUT)
    that receives a ZIP of the current CSV_data directory whenever we sync.
"""

from __future__ import annotations

import io
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Iterable, List

import requests

DATA_DIR = Path(os.getenv("AUTOSNIPER_DATA_DIR", "CSV_data"))

DATASET_PATHS: dict[str, Path] = {
    "all_vehicle_links.csv": Path("scrapers") / "all_vehicle_links.csv",
    "active_vehicle_links.csv": Path("scrapers") / "active_vehicle_links.csv",
    "raw_vehicle_data.csv": Path("scrapers") / "raw_vehicle_data.csv",
    "normalised_data.csv": Path("scrapers") / "normalised_data.csv",
    "vehicle_static_details.csv": Path("scrapers") / "vehicle_static_details.csv",
    "matched_canonical_details.csv": Path("scrapers") / "matched_canonical_details.csv",
    "unmatched_canonical_details.csv": Path("scrapers") / "unmatched_canonical_details.csv",
    "active_vehicle_details.csv": Path("scrapers") / "active_vehicle_details.csv",
    "sold_cars.csv": Path("scrapers") / "sold_cars.csv",
    "referred_cars.csv": Path("scrapers") / "referred_cars.csv",
    "active_snapshots.csv": Path("scrapers") / "active_snapshots.csv",
    "bid_history.csv": Path("scrapers") / "bid_history.csv",
    "bid_history_bidders.csv": Path("scrapers") / "bid_history_bidders.csv",
    "bid_history_listings.csv": Path("scrapers") / "bid_history_listings.csv",
    "bid_history_targets.csv": Path("scrapers") / "bid_history_targets.csv",
    "excluded_listings.csv": Path("scrapers") / "excluded_listings.csv",
    "scrape_failures.csv": Path("scrapers") / "scrape_failures.csv",
    "ai_listing_valuations.csv": Path("ai") / "ai_listing_valuations.csv",
    "ai_verdicts.csv": Path("ai") / "ai_verdicts.csv",
    "active_vehicle_details_restricted.csv": Path("restricted") / "active_vehicle_details_restricted.csv",
    "sold_cars_restricted.csv": Path("restricted") / "sold_cars_restricted.csv",
    "restricted_group_map.csv": Path("restricted") / "restricted_group_map.csv",
    "curves.csv": Path("restricted") / "curves.csv",
    "scored_listings.csv": Path("model_audit") / "scored_listings.csv",
    "scored_listings_enriched.csv": Path("model_audit") / "scored_listings_enriched.csv",
    "model_accuracy_weekly.csv": Path("model_audit") / "model_accuracy_weekly.csv",
    "model_accuracy_by_tier.csv": Path("model_audit") / "model_accuracy_by_tier.csv",
    "sold_cars_historical.csv": Path("archives") / "sold_cars_historical.csv",
    "sold_cars_rescraped.csv": Path("archives") / "sold_cars_rescraped.csv",
    "ai_analysis_ready": Path("archives") / "ai_analysis_ready",
    "repair_estimates.csv": Path("repairs") / "repair_estimates.csv",
}

REQUIRED_FILES: List[str] = [
    "vehicle_static_details.csv",
    "active_vehicle_details.csv",
    "all_vehicle_links.csv",
    "ai_listing_valuations.csv",
    "sold_cars.csv",
    "referred_cars.csv",
]

_SYNC_MARKER = DATA_DIR / ".remote_sync.json"


def _dataset_relpath(name: str) -> Path:
    path = Path(name)
    if len(path.parts) > 1:
        return path
    mapped = DATASET_PATHS.get(name)
    if mapped is not None:
        return mapped
    return path


def dataset_path(filename: str) -> Path:
    """Return the absolute path to a dataset within ``CSV_data``."""
    return DATA_DIR / _dataset_relpath(filename)


def _missing_required_files() -> list[str]:
    missing: list[str] = []
    for filename in REQUIRED_FILES:
        if not dataset_path(filename).exists():
            missing.append(filename)
    return missing


def _should_refresh(cache_minutes: int) -> bool:
    if cache_minutes <= 0:
        return True
    if not _SYNC_MARKER.exists():
        return True
    try:
        info = json.loads(_SYNC_MARKER.read_text(encoding="utf-8"))
    except Exception:
        return True
    timestamp = info.get("timestamp", 0)
    url = info.get("url")
    if url != os.getenv("AUTOSNIPER_DATA_URL"):
        return True
    return (time.time() - float(timestamp)) > cache_minutes * 60


def _extract_zip(content: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            member_path = Path(member.filename)
            if member_path.name == "":
                continue

            parts = list(member_path.parts)
            if parts and parts[0].lower() == "csv_data":
                parts = parts[1:]
            relative = Path(*parts)
            target_path = DATA_DIR / _dataset_relpath(relative.as_posix())
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, target_path.open("wb") as dst:
                dst.write(src.read())


def _download_remote_bundle() -> None:
    url = os.getenv("AUTOSNIPER_DATA_URL")
    if not url:
        return
    token = os.getenv("AUTOSNIPER_DATA_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    timeout = int(os.getenv("AUTOSNIPER_DATA_TIMEOUT", "30"))

    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    if url.lower().endswith(".zip") or "zip" in content_type:
        _extract_zip(response.content)
    else:
        # Treat as a single CSV target named the same as the remote file.
        filename = Path(url).name or "remote_dataset.csv"
        target = dataset_path(filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _SYNC_MARKER.write_text(
        json.dumps({"timestamp": time.time(), "url": url}, ensure_ascii=False),
        encoding="utf-8",
    )


def _build_zip_bytes(filenames: Iterable[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in filenames:
            relative = _dataset_relpath(name)
            path = DATA_DIR / relative
            if not path.exists():
                continue
            archive.write(path, arcname=Path("CSV_data") / relative)
    return buffer.getvalue()


def upload_remote_data_bundle(filenames: Iterable[str] | None = None) -> bool:
    """Upload a ZIP of CSV_data to AUTOSNIPER_DATA_UPLOAD_URL, if configured."""
    upload_url = os.getenv("AUTOSNIPER_DATA_UPLOAD_URL")
    if not upload_url:
        return False
    token = os.getenv("AUTOSNIPER_DATA_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    timeout = int(os.getenv("AUTOSNIPER_DATA_TIMEOUT", "30"))
    files_to_send = list(filenames) if filenames else REQUIRED_FILES
    try:
        payload = _build_zip_bytes(files_to_send)
        response = requests.put(upload_url, headers=headers, data=payload, timeout=timeout)
        response.raise_for_status()
        return True
    except Exception:
        # Avoid crashing the UI if upload fails.
        return False


def sync_remote_data(force: bool = False) -> None:
    """Fetch the remote dataset bundle when configured."""
    if not os.getenv("AUTOSNIPER_DATA_URL"):
        return
    cache_minutes = int(os.getenv("AUTOSNIPER_DATA_CACHE_MINUTES", "30"))
    if force or _should_refresh(cache_minutes) or _missing_required_files():
        _download_remote_bundle()


_last_sync_time: float = 0.0


def _sync_once() -> None:
    """Sync at most once per cache window within this process lifetime."""
    global _last_sync_time
    cache_minutes = int(os.getenv("AUTOSNIPER_DATA_CACHE_MINUTES", "30"))
    elapsed_minutes = (time.time() - _last_sync_time) / 60.0
    if _last_sync_time == 0.0 or elapsed_minutes >= cache_minutes or _missing_required_files():
        sync_remote_data(force=False)
        _last_sync_time = time.time()


def ensure_datasets_available(required: Iterable[str] | None = None) -> list[str]:
    """Ensure that all required datasets exist locally.

    Returns a list of missing filenames (empty when everything is available).
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _sync_once()
    filenames = list(required) if required is not None else REQUIRED_FILES
    missing: list[str] = []
    for filename in filenames:
        if not dataset_path(filename).exists():
            missing.append(filename)
    return missing
