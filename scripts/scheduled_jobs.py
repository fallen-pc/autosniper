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
from playwright.async_api import Error as PlaywrightError, async_playwright

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
from shared.telegram_alerts import send_on_state_change, send_telegram_message

CHECK_URL = os.getenv("AUTOSNIPER_HEALTHCHECK_URL", "https://www.grays.com/")
CHECK_INTERVAL_SECONDS = int(os.getenv("AUTOSNIPER_NET_CHECK_INTERVAL_SEC", "300"))
MAX_WAIT_HOURS = int(os.getenv("AUTOSNIPER_MAX_WAIT_HOURS", "24"))
GOVERNANCE_REPORT_DIR = ROOT_DIR / "output" / "governance"
METRICS_PATH = ROOT_DIR / "status" / "metrics.json"
DAILY_STATE_PATH = ROOT_DIR / "status" / "daily_run_state.json"
RUNTIME_BACKUP_SCRIPT = ROOT_DIR / "scripts" / "backup_runtime_data.ps1"
AUTOTRADER_SEED_URLS_PATH = ROOT_DIR / "autotrader_isolated" / "seed_urls.txt"
PLAYWRIGHT_MISSING_BROWSER_MARKERS = (
    "executable doesn't exist",
    "please run the following command to download new browsers",
    "playwright install",
)

LOCK_PATH = ROOT_DIR / "logs" / "scrape.lock"
LOCK_TTLS = {
    "daily": 8,
    "daily-smoke": 2,
    "hourly-monitor": 2,
    "vic-12h": 4,
    "vic-hourly": 2,
}

COMPLETED_STATUSES = {"sold", "referred", "canceled", "cancelled", "closed"}


def _env_flag_enabled(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_flag_disabled(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"0", "false", "no", "n", "off"}


async def _probe_playwright_chromium() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        await browser.close()


def _is_missing_playwright_browser_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in PLAYWRIGHT_MISSING_BROWSER_MARKERS)


def _ensure_playwright_chromium_available() -> None:
    try:
        asyncio.run(_probe_playwright_chromium())
        return
    except PlaywrightError as exc:
        if not _is_missing_playwright_browser_error(exc):
            raise
        if _env_flag_disabled("AUTOSNIPER_PLAYWRIGHT_AUTO_INSTALL"):
            raise RuntimeError(
                "Playwright Chromium is missing. Run "
                f"`{sys.executable} -m playwright install chromium` or set "
                "AUTOSNIPER_PLAYWRIGHT_AUTO_INSTALL=1 to allow scheduled jobs to repair it."
            ) from exc

    command = [sys.executable, "-m", "playwright", "install", "chromium"]
    print("Playwright Chromium is missing; installing before starting scheduled scrape work.")
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Playwright Chromium is missing and automatic installation failed. "
            f"Run `{' '.join(command)}` manually and retry the scheduled job."
        ) from exc

    try:
        asyncio.run(_probe_playwright_chromium())
    except PlaywrightError as exc:
        raise RuntimeError(
            "Playwright Chromium installation completed, but the browser still cannot launch."
        ) from exc


def _run_playwright_preflight(job: str) -> None:
    try:
        _ensure_playwright_chromium_available()
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        write_scraper_health_report(job_name=job, job_status="failure", error_message=error_message)
        if job == "daily":
            _record_daily_run_finish(
                trigger="scheduled",
                coverage_date_local=_coverage_date_for_explicit_daily_run(),
                success=False,
                error_message=error_message,
            )
        _send_job_failure_alert(job, error_message)
        raise


def _run_runtime_backup_if_configured() -> None:
    backup_dir = str(os.getenv("AUTOSNIPER_BACKUP_DIR") or "").strip()
    if not backup_dir:
        print("Runtime backup skipped: AUTOSNIPER_BACKUP_DIR is not set.")
        return
    if not RUNTIME_BACKUP_SCRIPT.exists():
        raise FileNotFoundError(f"Missing runtime backup script: {RUNTIME_BACKUP_SCRIPT}")

    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUNTIME_BACKUP_SCRIPT),
        "-BackupDir",
        backup_dir,
    ]
    if _env_flag_enabled("AUTOSNIPER_BACKUP_INCLUDE_AUTOTRADER_SESSION"):
        command.append("-IncludeAutotraderSession")
    subprocess.run(command, check=True)


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


def _daily_catchup_grace_minutes() -> int:
    raw = os.getenv("AUTOSNIPER_DAILY_CATCHUP_GRACE_MINUTES", "30").strip() or "30"
    try:
        value = int(raw)
    except ValueError:
        return 30
    return max(value, 0)


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


def _last_successful_daily_date_local() -> date | None:
    state = _load_daily_run_state()
    explicit = _parse_iso_date(state.get("last_success_coverage_date_local"))
    if explicit is not None:
        return explicit
    if str(state.get("last_status") or "").strip().lower() == "success":
        explicit = _parse_iso_date(state.get("last_coverage_date_local"))
        if explicit is not None:
            return explicit
    metrics = _load_existing_metrics()
    metrics_time = _parse_iso_datetime(metrics.get("last_run_utc"))
    if metrics_time is None:
        return None
    return metrics_time.astimezone(_local_timezone()).date()


def _read_lock_payload() -> Dict[str, Any] | None:
    try:
        return json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _active_daily_run_covers_date(coverage_date_local: date) -> bool:
    state = _load_daily_run_state()
    lock_state_running = (
        str(state.get("last_status") or "").strip().lower() == "running"
        and _parse_iso_date(state.get("last_coverage_date_local")) == coverage_date_local
    )
    payload = _read_lock_payload()
    if payload is None:
        return False
    if str(payload.get("job") or "").strip() != "daily":
        return False
    try:
        age = time.time() - LOCK_PATH.stat().st_mtime
    except FileNotFoundError:
        return False
    if age > _existing_lock_ttl_hours() * 3600:
        return False
    lock_date = datetime.fromtimestamp(LOCK_PATH.stat().st_mtime, tz=_local_timezone()).date()
    return lock_state_running or lock_date == coverage_date_local


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


def _record_daily_run_skip(*, trigger: str, coverage_date_local: date, reason: str) -> None:
    state = _load_daily_run_state()
    completed_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    state.update(
        {
            "last_completed_utc": completed_utc,
            "last_status": "skipped",
            "last_trigger": trigger,
            "last_coverage_date_local": coverage_date_local.isoformat(),
            "last_error_message": reason.strip(),
        }
    )
    state["last_skipped_utc"] = completed_utc
    state["last_skipped_coverage_date_local"] = coverage_date_local.isoformat()
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
    local_now = _now_local(now)
    target_date = _latest_due_daily_date_local(local_now)
    grace_minutes = _daily_catchup_grace_minutes()
    if grace_minutes > 0 and local_now.date() == target_date:
        schedule_local = _daily_schedule_time_local()
        schedule_dt_local = datetime.combine(target_date, schedule_local, tzinfo=local_now.tzinfo)
        grace_deadline_local = schedule_dt_local + timedelta(minutes=grace_minutes)
        if schedule_dt_local <= local_now < grace_deadline_local:
            return False, target_date
    last_successful = _last_successful_daily_date_local()
    if last_successful is not None and last_successful >= target_date:
        return False, target_date
    if _active_daily_run_covers_date(target_date):
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
    except Exception as exc:
        print(f"WARNING: job-failure Telegram alert did not send: {type(exc).__name__}: {exc}")
        return


def _action_counts_text(df: pd.DataFrame) -> str:
    counts = df["action_label"].fillna("").astype(str).str.strip().value_counts().to_dict()
    ordered = ["Buy", "Watch", "Avoid", "Review"]
    parts = [f"{label} {int(counts.get(label, 0))}" for label in ordered]
    other_count = sum(int(count) for label, count in counts.items() if label and label not in ordered)
    if other_count:
        parts.append(f"Other {other_count}")
    return " | ".join(parts)


def _bid_status_counts_text(df: pd.DataFrame) -> str:
    if "bid_status" not in df.columns:
        return "N/A"
    counts = df["bid_status"].fillna("").astype(str).str.strip().value_counts()
    parts = [f"{label} {int(count)}" for label, count in counts.items() if label]
    return " | ".join(parts[:5]) if parts else "N/A"


def _load_daily_ai_analysis_frame() -> pd.DataFrame:
    path = dataset_path("ai_listing_valuations.csv")
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    if "analysis_context" in df.columns:
        active_mask = df["analysis_context"].fillna("").astype(str).str.strip().str.lower() == "active"
        df = df[active_mask].copy()
    active_path = dataset_path("active_vehicle_details.csv")
    if active_path.exists() and "url" in df.columns:
        try:
            active_df = pd.read_csv(active_path, usecols=["url"], low_memory=False)
        except Exception:
            active_df = pd.DataFrame()
        if not active_df.empty and "url" in active_df.columns:
            active_urls = set(active_df["url"].dropna().astype(str).str.strip())
            df = df[df["url"].astype(str).str.strip().isin(active_urls)].copy()
    return df


def _send_daily_ai_analysis_summary(*, trigger: str, coverage_date_local: date) -> bool:
    try:
        df = _load_daily_ai_analysis_frame()
        if df.empty:
            message = (
                "AutoSniper daily status\n"
                f"Date: {coverage_date_local.isoformat()}\n"
                f"Run: {trigger}\n"
                "Current active AI rows: 0\n"
                "Result: No current active listings have fresh AI Analysis rows.\n"
                "Meaning: Telegram is working, but there are no current AI Analysis candidates to report. "
                "This usually means the valuation cache is stale or no current active listings are in AI Analysis scope."
            )
            verdict = "No active AI Analysis rows"
        else:
            if "action_label" not in df.columns:
                df["action_label"] = ""
            buy_count = int((df["action_label"].fillna("").astype(str).str.strip() == "Buy").sum())
            verdict = f"Buy {buy_count}"
            message = (
                "AutoSniper daily status\n"
                f"Date: {coverage_date_local.isoformat()}\n"
                f"Run: {trigger}\n"
                f"Current active AI rows: {len(df)}\n"
                f"AI actions: {_action_counts_text(df)}\n"
                f"Bid positions: {_bid_status_counts_text(df)}\n"
                + (
                    "Result: No Buy candidates in current active AI Analysis."
                    if buy_count == 0
                    else f"Result: {buy_count} Buy candidate(s). Individual listing alerts are sent separately."
                )
            )
        sent = send_on_state_change(
            "daily_ai_analysis_summary",
            "autosniper-daily-ai-analysis-summary",
            coverage_date_local.isoformat(),
            message,
            verdict=verdict,
        )
        print(f"Daily AI Analysis Telegram summary sent={sent}, verdict={verdict}.")
        return sent
    except Exception:
        print("Daily AI Analysis Telegram summary failed.")
        return False


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


def _existing_lock_ttl_hours() -> int:
    try:
        payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return max(max(LOCK_TTLS.values(), default=4), 4)
    owner_job = str(payload.get("job") or "").strip()
    return LOCK_TTLS.get(owner_job, max(max(LOCK_TTLS.values(), default=4), 4))


def _acquire_lock(job: str) -> bool:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
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
            ttl_hours = _existing_lock_ttl_hours()
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
    update_master.update_master_database()
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
        "--urls-file",
        str(AUTOTRADER_SEED_URLS_PATH),
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
        if _active_daily_run_covers_date(coverage_date_local):
            return
        _record_daily_run_skip(
            trigger=trigger,
            coverage_date_local=coverage_date_local,
            reason="Lock busy; skipped daily run.",
        )
        return

    started = time.time()
    _record_daily_run_start(trigger=trigger, coverage_date_local=coverage_date_local)
    try:
        run_daily_pipeline()
        _run_runtime_backup_if_configured()
        write_scraper_health_report(job_name="daily" if trigger == "scheduled" else f"daily-{trigger}", job_status="success")
        _record_daily_run_finish(trigger=trigger, coverage_date_local=coverage_date_local, success=True)
        _write_daily_metrics(success=True, duration_sec=time.time() - started)
        _send_daily_ai_analysis_summary(trigger=trigger, coverage_date_local=coverage_date_local)
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

    _run_playwright_preflight(args.job)

    if args.job not in {"daily", "daily-smoke"} and _run_missed_daily_catchup_if_due(args.job):
        return

    if args.job == "daily":
        _run_daily_job(trigger="scheduled", coverage_date_local=_coverage_date_for_explicit_daily_run())
        return

    if not _acquire_lock(args.job):
        return

    try:
        if args.job == "daily-smoke":
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
