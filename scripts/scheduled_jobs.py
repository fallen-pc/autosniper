from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
import subprocess

import pandas as pd
import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import extract_links, extract_vehicle_details, update_bids, update_master
from scripts.active_monitor import (
    active_urls_from_frame,
    diff_price_changed_listing_urls,
    load_ai_analysis_active_df,
    revalue_active_listings,
)
from scripts.outcome_tracking import compute_outcome_metrics
from shared.data_loader import dataset_path
from shared.governance import write_governance_report_bundle
from shared.sold_cleaning import is_compliance_slug, normalize_listing_fields
from shared.scraper_health import write_scraper_health_report
from shared.telegram_alerts import send_telegram_message

CHECK_URL = os.getenv("AUTOSNIPER_HEALTHCHECK_URL", "https://www.grays.com/")
CHECK_INTERVAL_SECONDS = int(os.getenv("AUTOSNIPER_NET_CHECK_INTERVAL_SEC", "300"))
MAX_WAIT_HOURS = int(os.getenv("AUTOSNIPER_MAX_WAIT_HOURS", "24"))
GOVERNANCE_REPORT_DIR = ROOT_DIR / "output" / "governance"
METRICS_PATH = ROOT_DIR / "status" / "metrics.json"

LOCK_PATH = ROOT_DIR / "logs" / "scrape.lock"
LOCK_TTLS = {
    "daily": 8,
    "hourly-monitor": 2,
    "vic-12h": 4,
    "vic-hourly": 2,
}

COMPLETED_STATUSES = {"sold", "referred", "canceled", "cancelled", "closed"}


def _load_existing_metrics() -> Dict[str, Any]:
    if not METRICS_PATH.exists():
        return {}
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _count_active_listings() -> Optional[int]:
    path = dataset_path("active_vehicle_details.csv")
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, low_memory=False)
        return int(len(df))
    except Exception:
        return None


def _write_daily_metrics(success: bool, duration_sec: float) -> None:
    metrics = _load_existing_metrics()
    active_listings = _count_active_listings()
    runs_total = int(metrics.get("runs_total", 0)) + 1
    runs_failed = int(metrics.get("runs_failed", 0)) + (0 if success else 1)
    payload = {
        "last_run_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "active_listings": int(active_listings) if active_listings is not None else int(metrics.get("active_listings", 0)),
        "runs_total": runs_total,
        "runs_failed": runs_failed,
        "duration_sec": float(duration_sec),
    }
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _send_job_failure_alert(job: str, detail: str) -> None:
    detail_text = str(detail).strip()
    if not detail_text:
        return
    message = (
        "Pipeline failure\n"
        f"Job: {job}\n"
        f"Time: {datetime.now(timezone.utc).isoformat()}\n"
        f"Detail: {detail_text}"
    )
    try:
        send_telegram_message(message)
    except Exception:
        return


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


def _run_update_bids(urls: Iterable[str], *, skip_master: bool = True) -> None:
    url_list = list(urls)
    if not url_list:
        print("No URLs found to update.")
        return
    asyncio.run(
        update_bids.update_bids(
            input_links=url_list,
            limit=len(url_list),
            skip_master=skip_master,
        )
    )


def run_daily_pipeline() -> None:
    extract_links.extract_all_vehicle_links()
    extract_vehicle_details.main()
    asyncio.run(update_bids.update_bids(skip_master=True))
    _run_autotrader_scrape()
    update_master.update_master_database()
    revalue_active_listings(stale_minutes=0, force_refresh=True)
    report_bundle = write_governance_report_bundle(GOVERNANCE_REPORT_DIR)
    compute_outcome_metrics()
    coverage_summary = report_bundle["coverage_summary"]
    monotonicity_summary = report_bundle["monotonicity_summary"]
    print(
        "Governance reports updated: "
        f"coverage missing={coverage_summary['missing_tags']}, "
        f"monotonicity errors={monotonicity_summary['errors']}, "
        f"warnings={monotonicity_summary['warnings']}."
    )


def run_hourly_monitor() -> None:
    before_df = load_ai_analysis_active_df()
    urls = active_urls_from_frame(before_df)
    _run_update_bids(urls, skip_master=True)
    after_df = load_ai_analysis_active_df()
    price_changed_urls = diff_price_changed_listing_urls(before_df, after_df)
    summary = revalue_active_listings(target_urls=price_changed_urls, stale_minutes=60, force_refresh=True)
    print(
        "Hourly monitor complete: "
        f"{len(price_changed_urls):,} price-changed URLs, {int(summary.get('evaluated', 0)):,} listings revalued."
    )


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


def _run_autotrader_scrape() -> None:
    script_path = ROOT_DIR / "scripts" / "run_autotrader_scrape.ps1"
    if not script_path.exists():
        raise FileNotFoundError(f"Autotrader scrape script not found: {script_path}")
    subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        check=True,
    )
    print("Autotrader scrape completed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scheduled scraping jobs. This is the primary production runner.")
    parser.add_argument(
        "--job",
        choices=("daily", "hourly-monitor", "vic-12h", "vic-hourly"),
        required=True,
        help="Job name to run.",
    )
    args = parser.parse_args()

    if not _wait_for_internet(MAX_WAIT_HOURS):
        message = "No internet within max wait window; exiting."
        print(message)
        write_scraper_health_report(job_name=args.job, job_status="failure", error_message=message)
        _send_job_failure_alert(args.job, message)
        return

    if not _acquire_lock(args.job):
        return

    started = time.time()
    try:
        if args.job == "daily":
            run_daily_pipeline()
        elif args.job == "hourly-monitor":
            run_hourly_monitor()
        elif args.job == "vic-12h":
            run_vic_refresh_12h()
        elif args.job == "vic-hourly":
            run_vic_refresh_hourly()
        write_scraper_health_report(job_name=args.job, job_status="success")
        if args.job == "daily":
            _write_daily_metrics(success=True, duration_sec=time.time() - started)
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        write_scraper_health_report(job_name=args.job, job_status="failure", error_message=error_message)
        _send_job_failure_alert(args.job, error_message)
        if args.job == "daily":
            _write_daily_metrics(success=False, duration_sec=time.time() - started)
        raise
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
