from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
import subprocess
from zoneinfo import ZoneInfo

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
DAILY_STATE_PATH = ROOT_DIR / "status" / "daily_run_state.json"

LOCK_PATH = ROOT_DIR / "logs" / "scrape.lock"
LOCK_TTLS = {
    "daily": 8,
    "daily-smoke": 2,
    "hourly-monitor": 2,
    "vic-12h": 4,
    "vic-hourly": 2,
}

COMPLETED_STATUSES = {"sold", "referred", "canceled", "cancelled", "closed"}


def _local_timezone() -> timezone | ZoneInfo:
    timezone_name = os.getenv("AUTOSNIPER_LOCAL_TIMEZONE", "Australia/Sydney").strip() or "Australia/Sydney"
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return timezone.utc


def _daily_schedule_time_local() -> dt_time:
    raw = os.getenv("AUTOSNIPER_DAILY_SCHEDULE_LOCAL_TIME", "09:00").strip() or "09:00"
    try:
        hour_text, minute_text = raw.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return dt_time(hour=hour, minute=minute)
    except ValueError:
        return dt_time(hour=9, minute=0)


def _now_local(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(_local_timezone())


def _latest_due_daily_date_local(now: datetime | None = None) -> date:
    local_now = _now_local(now)
    due_date = local_now.date()
    if local_now.time() < _daily_schedule_time_local():
        due_date -= timedelta(days=1)
    return due_date


def _coverage_date_for_explicit_daily_run(now: datetime | None = None) -> date:
    return _now_local(now).date()


def _load_daily_run_state() -> Dict[str, Any]:
    if not DAILY_STATE_PATH.exists():
        return {}
    try:
        return json.loads(DAILY_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_daily_run_state(payload: Dict[str, Any]) -> None:
    DAILY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DAILY_STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _last_attempted_daily_date_local() -> date | None:
    state = _load_daily_run_state()
    explicit = _parse_iso_date(state.get("last_coverage_date_local"))
    if explicit is not None:
        return explicit
    metrics = _load_existing_metrics()
    metrics_time = _parse_iso_datetime(metrics.get("last_run_utc"))
    if metrics_time is None:
        return None
    return metrics_time.astimezone(_local_timezone()).date()


def _record_daily_run_start(*, trigger: str, coverage_date_local: date) -> None:
    state = _load_daily_run_state()
    state.update(
        {
            "last_started_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "last_status": "running",
            "last_trigger": trigger,
            "last_coverage_date_local": coverage_date_local.isoformat(),
            "last_error_message": "",
        }
    )
    _write_daily_run_state(state)


def _record_daily_run_finish(
    *,
    trigger: str,
    coverage_date_local: date,
    success: bool,
    error_message: str = "",
) -> None:
    state = _load_daily_run_state()
    completed_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    state.update(
        {
            "last_completed_utc": completed_utc,
            "last_status": "success" if success else "failure",
            "last_trigger": trigger,
            "last_coverage_date_local": coverage_date_local.isoformat(),
            "last_error_message": error_message.strip(),
        }
    )
    if success:
        state["last_success_utc"] = completed_utc
        state["last_success_coverage_date_local"] = coverage_date_local.isoformat()
    else:
        state["last_failure_utc"] = completed_utc
        state["last_failure_coverage_date_local"] = coverage_date_local.isoformat()
    _write_daily_run_state(state)


def _should_run_missed_daily_catchup(now: datetime | None = None) -> tuple[bool, date]:
    enabled = os.getenv("AUTOSNIPER_ENABLE_MISSED_DAILY_CATCHUP", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return False, _latest_due_daily_date_local(now)
    target_date = _latest_due_daily_date_local(now)
    last_attempted = _last_attempted_daily_date_local()
    if last_attempted is not None and last_attempted >= target_date:
        return False, target_date
    return True, target_date


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


def _run_autotrader_scrape(max_pages: int | None = None) -> None:
    storage_state = ROOT_DIR / "autotrader_isolated" / "output" / "storage_state.json"
    cookie_file = ROOT_DIR / "autotrader_isolated" / "output" / "autotrader_cookie.txt"
    if not storage_state.exists():
        raise FileNotFoundError(f"Missing Autotrader storage state: {storage_state}")
    if not cookie_file.exists():
        raise FileNotFoundError(f"Missing Autotrader cookie file: {cookie_file}")

    command = [
        sys.executable,
        "autotrader_isolated/scrape_first_page.py",
        "--all-pages",
        "--playwright-headful",
        "--playwright-browser",
        "chrome",
        "--storage-state",
        str(storage_state),
        "--cookie-file",
        str(cookie_file),
        "--page-retries",
        "3",
        "--page-retry-delay",
        "10",
    ]
    if max_pages is not None and max_pages > 0:
        command.extend(["--max-pages", str(max_pages)])
    subprocess.run(command, check=True)
    print("Autotrader scrape completed.")


def run_daily_smoke() -> None:
    """Run a limited end-to-end pipeline proof without doing a full daily scrape."""
    detail_limit = max(1, int(os.getenv("AUTOSNIPER_DAILY_SMOKE_DETAIL_LIMIT", "5")))
    autotrader_pages = max(1, int(os.getenv("AUTOSNIPER_DAILY_SMOKE_AUTOTRADER_PAGES", "1")))

    print(
        "Daily smoke limits: "
        f"detail_limit={detail_limit}, autotrader_pages={autotrader_pages}. "
        "Grays link extraction runs full so the active queue is not narrowed."
    )
    extract_links.extract_all_vehicle_links()
    extract_vehicle_details.main(
        batch_size=detail_limit,
        checkpoint_every=detail_limit,
    )
    before_df = load_ai_analysis_active_df()
    urls = active_urls_from_frame(before_df)
    _run_update_bids(urls, skip_master=True)
    _run_autotrader_scrape(max_pages=autotrader_pages)
    update_master.update_master_database()
    after_df = load_ai_analysis_active_df()
    price_changed_urls = diff_price_changed_listing_urls(before_df, after_df)
    summary = revalue_active_listings(
        target_urls=price_changed_urls or set(urls),
        stale_minutes=60,
        force_refresh=True,
    )
    report_bundle = write_governance_report_bundle(GOVERNANCE_REPORT_DIR)
    compute_outcome_metrics()
    coverage_summary = report_bundle["coverage_summary"]
    monotonicity_summary = report_bundle["monotonicity_summary"]
    print(
        "Daily smoke complete: "
        f"{len(urls):,} monitored URLs, "
        f"{len(price_changed_urls):,} price-changed URLs, "
        f"{int(summary.get('evaluated', 0)):,} listings revalued, "
        f"coverage missing={coverage_summary['missing_tags']}, "
        f"monotonicity errors={monotonicity_summary['errors']}."
    )


def _run_daily_job(*, trigger: str, coverage_date_local: date) -> None:
    if not _acquire_lock("daily"):
        return

    started = time.time()
    _record_daily_run_start(trigger=trigger, coverage_date_local=coverage_date_local)
    try:
        run_daily_pipeline()
        write_scraper_health_report(job_name="daily" if trigger == "scheduled" else f"daily-{trigger}", job_status="success")
        _record_daily_run_finish(trigger=trigger, coverage_date_local=coverage_date_local, success=True)
        _write_daily_metrics(success=True, duration_sec=time.time() - started)
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        write_scraper_health_report(
            job_name="daily" if trigger == "scheduled" else f"daily-{trigger}",
            job_status="failure",
            error_message=error_message,
        )
        _record_daily_run_finish(
            trigger=trigger,
            coverage_date_local=coverage_date_local,
            success=False,
            error_message=error_message,
        )
        _send_job_failure_alert("daily" if trigger == "scheduled" else f"daily-{trigger}", error_message)
        _write_daily_metrics(success=False, duration_sec=time.time() - started)
        raise
    finally:
        _release_lock()


def _run_missed_daily_catchup_if_due(trigger_job: str) -> bool:
    should_run, coverage_date_local = _should_run_missed_daily_catchup()
    if not should_run:
        return False
    print(
        "Missed daily run detected; "
        f"starting catch-up for local date {coverage_date_local.isoformat()} before {trigger_job}."
    )
    _run_daily_job(trigger="catchup", coverage_date_local=coverage_date_local)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scheduled scraping jobs. This is the primary production runner.")
    parser.add_argument(
        "--job",
        choices=("daily", "daily-smoke", "hourly-monitor", "vic-12h", "vic-hourly"),
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

    if args.job not in {"daily", "daily-smoke"} and _run_missed_daily_catchup_if_due(args.job):
        return

    if args.job == "daily":
        _run_daily_job(trigger="scheduled", coverage_date_local=_coverage_date_for_explicit_daily_run())
        return

    if not _acquire_lock(args.job):
        return

    started = time.time()
    try:
        if args.job == "daily":
            run_daily_pipeline()
        elif args.job == "daily-smoke":
            run_daily_smoke()
        elif args.job == "hourly-monitor":
            run_hourly_monitor()
        elif args.job == "vic-12h":
            run_vic_refresh_12h()
        elif args.job == "vic-hourly":
            run_vic_refresh_hourly()
        write_scraper_health_report(job_name=args.job, job_status="success")
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        write_scraper_health_report(job_name=args.job, job_status="failure", error_message=error_message)
        _send_job_failure_alert(args.job, error_message)
        raise
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
