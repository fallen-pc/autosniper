"""Utilities for ensuring the CSV datasets are present locally.

This module allows the app to pull a ZIP bundle of CSV files from a remote
location defined by environment variables. It keeps the repository light while
still supporting “live” data in hosted environments such as Streamlit Cloud.

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
    is re-downloaded. While the cache is “warm”, extraction is skipped unless
    files are missing.
"""

from __future__ import annotations

import io
import json
import os
import time
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List

import requests

DATA_DIR = Path(os.getenv("AUTOSNIPER_DATA_DIR", "CSV_data"))

REQUIRED_FILES: List[str] = [
    "vehicle_static_details.csv",
    "active_vehicle_details.csv",
    "all_vehicle_links.csv",
    "ai_verdicts.csv",
    "ai_listing_valuations.csv",
    "sold_cars.csv",
    "referred_cars.csv",
]

_SYNC_MARKER = DATA_DIR / ".remote_sync.json"


def dataset_path(filename: str) -> Path:
    """Return the absolute path to a dataset within ``CSV_data``."""
    return DATA_DIR / filename


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
            target_path = DATA_DIR.joinpath(*parts)
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


def sync_remote_data(force: bool = False) -> None:
    """Fetch the remote dataset bundle when configured."""
    if not os.getenv("AUTOSNIPER_DATA_URL"):
        return
    cache_minutes = int(os.getenv("AUTOSNIPER_DATA_CACHE_MINUTES", "30"))
    if force or _should_refresh(cache_minutes) or _missing_required_files():
        _download_remote_bundle()


@lru_cache(maxsize=1)
def _sync_once() -> None:
    sync_remote_data(force=False)


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

