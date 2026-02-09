from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import extract_links, extract_vehicle_details, update_bids, update_master
from shared.data_loader import dataset_path
from shared.sold_cleaning import is_compliance_slug, normalize_listing_fields

CHECK_URL = os.getenv("AUTOSNIPER_HEALTHCHECK_URL", "https://www.grays.com/")
CHECK_INTERVAL_SECONDS = int(os.getenv("AUTOSNIPER_NET_CHECK_INTERVAL_SEC", "300"))
MAX_WAIT_HOURS = int(os.getenv("AUTOSNIPER_MAX_WAIT_HOURS", "24"))

LOCK_PATH = ROOT_DIR / "logs" / "scrape.lock"
LOCK_TTLS = {
    "daily": 8,
    "vic-12h": 4,
    "vic-hourly": 2,
}

COMPLETED_STATUSES = {"sold", "referred", "canceled", "cancelled", "closed"}


def _has_internet() -> bool:
    try:
        requests.get(CHECK_URL, timeout=10)
        return True
    except requests.RequestException:
        return False


def _wait_for_internet(max_wait_hours: int) -> bool:
    start = time.monotonic()
    while True:
        if _has_internet():
            return True
        waited = time.monotonic() - start
        if waited >= max_wait_hours * 3600:
            return False
        print("No internet connection detected; retrying soon.")
        time.sleep(CHECK_INTERVAL_SECONDS)


def _acquire_lock(job: str) -> bool:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    ttl_hours = LOCK_TTLS.get(job, 4)
    while True:
        try:
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = {
                "job": job,
                "started_at": time.time(),
            }
            os.write(fd, json.dumps(payload).encode("utf-8"))
            os.close(fd)
            return True
        except FileExistsError:
            try:
                age = time.time() - LOCK_PATH.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > ttl_hours * 3600:
                try:
                    LOCK_PATH.unlink()
                    continue
                except FileNotFoundError:
                    continue
            print(f"Lock busy; skipping {job} run.")
            return False


def _release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def _load_active_df() -> pd.DataFrame:
    path = dataset_path("active_vehicle_details.csv")
    if not path.exists():
        print(f"Missing {path}; nothing to update.")
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    if df.empty:
        print("Active listings dataset is empty.")
        return df
    return normalize_listing_fields(df)


def _filter_vic(df: pd.DataFrame) -> pd.DataFrame:
    if "location" not in df.columns:
        return pd.DataFrame()
    vic_mask = df["location"].astype(str).str.upper().str.contains("VIC", na=False)
    return df[vic_mask].copy()


def _filter_active_status(df: pd.DataFrame) -> pd.DataFrame:
    if "status" not in df.columns:
        return df
    statuses = df["status"].astype(str).str.lower().str.strip()
    mask = ~statuses.isin(COMPLETED_STATUSES)
    return df[mask].copy()


def _filter_under_24h(df: pd.DataFrame) -> pd.DataFrame:
    if "time_remaining_or_date_sold" not in df.columns:
        return pd.DataFrame()
    hours = df["time_remaining_or_date_sold"].apply(update_bids.parse_time_remaining_to_hours)
    mask = hours.notna() & (hours > 0) & (hours <= 24)
    return df[mask].copy()


def _extract_urls(df: pd.DataFrame) -> list[str]:
    if df.empty or "url" not in df.columns:
        return []
    urls = [
        url
        for url in df["url"].dropna().astype(str).tolist()
        if url.startswith("http") and not is_compliance_slug(url)
    ]
    return sorted(set(urls))


def _run_update_bids(urls: Iterable[str]) -> None:
    url_list = list(urls)
    if not url_list:
        print("No URLs found to update.")
        return
    asyncio.run(update_bids.update_bids(input_links=url_list, limit=len(url_list)))


def run_daily_pipeline() -> None:
    extract_links.extract_all_vehicle_links()
    extract_vehicle_details.main()
    asyncio.run(update_bids.update_bids())
    update_master.update_master_database()


def run_vic_refresh_12h() -> None:
    df = _load_active_df()
    df = _filter_vic(df)
    df = _filter_active_status(df)
    urls = _extract_urls(df)
    _run_update_bids(urls)
    update_master.update_master_database()


def run_vic_refresh_hourly() -> None:
    df = _load_active_df()
    df = _filter_vic(df)
    df = _filter_active_status(df)
    df = _filter_under_24h(df)
    urls = _extract_urls(df)
    _run_update_bids(urls)
    update_master.update_master_database()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scheduled scraping jobs.")
    parser.add_argument(
        "--job",
        choices=("daily", "vic-12h", "vic-hourly"),
        required=True,
        help="Job name to run.",
    )
    args = parser.parse_args()

    if not _wait_for_internet(MAX_WAIT_HOURS):
        print("No internet within max wait window; exiting.")
        return

    if not _acquire_lock(args.job):
        return

    try:
        if args.job == "daily":
            run_daily_pipeline()
        elif args.job == "vic-12h":
            run_vic_refresh_12h()
        elif args.job == "vic-hourly":
            run_vic_refresh_hourly()
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
