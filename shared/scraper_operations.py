"""Read-only scraper operations snapshot for the VPS landing page."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parent.parent
SYDNEY_TZ = ZoneInfo("Australia/Sydney")
DAILY_RUN_HOUR = 9
FRESH_HOURS = 36


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except (OSError, ValueError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def _modified_at(path: Path) -> datetime | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _hours_old(path: Path, now: datetime) -> float | None:
    modified = _modified_at(path)
    if modified is None:
        return None
    return max(0.0, (now - modified).total_seconds() / 3600)


def _format_local(value: datetime | str | None) -> str:
    if value is None or value == "":
        return "Never"
    parsed: datetime | None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return "Unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SYDNEY_TZ).strftime("%d %b %Y, %I:%M %p")


def _next_daily_run(now: datetime) -> datetime:
    local_now = now.astimezone(SYDNEY_TZ)
    next_run = local_now.replace(hour=DAILY_RUN_HOUR, minute=0, second=0, microsecond=0)
    if next_run <= local_now:
        next_run += timedelta(days=1)
    return next_run


def _next_hourly_run(now: datetime) -> datetime:
    local_now = now.astimezone(SYDNEY_TZ)
    next_run = local_now.replace(minute=13, second=0, microsecond=0)
    if next_run <= local_now:
        next_run += timedelta(hours=1)
    return next_run


def _present_count(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    values = frame[column]
    return int(
        (
            values.notna()
            & values.astype(str).str.strip().ne("")
            & values.astype(str).str.lower().ne("nan")
        ).sum()
    )


def _audit_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _status_for_file(
    path: Path,
    *,
    rows: int,
    now: datetime,
    enabled: bool = True,
) -> tuple[str, str]:
    if not enabled:
        return "Disabled", "Disabled in the VPS environment"
    age_hours = _hours_old(path, now)
    if rows <= 0 or age_hours is None:
        return "Failed", "No usable output is available"
    if age_hours > FRESH_HOURS:
        return "Stale", f"Last output is {age_hours:.0f} hours old"
    return "Healthy", "Latest output is available"


def _source_row(
    source: str,
    status: str,
    detail: str,
    path: Path,
    now: datetime,
    *,
    discovered: int = 0,
    parsed: int = 0,
    curve_matches: int = 0,
    priced: int = 0,
    errors: int = 0,
) -> dict[str, Any]:
    return {
        "source": source,
        "status": status,
        "detail": detail,
        "last_output": _format_local(_modified_at(path)),
        "age_hours": _hours_old(path, now),
        "discovered": int(discovered),
        "parsed": int(parsed),
        "curve_matches": int(curve_matches),
        "priced": int(priced),
        "errors": int(errors),
    }


def build_scraper_operations_snapshot(
    *,
    root_dir: Path = ROOT_DIR,
    now: datetime | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a bounded, operator-facing snapshot without mutating runtime state."""

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    env = environment if environment is not None else os.environ

    scraper_dir = root_dir / "CSV_data" / "scrapers"
    external_dir = root_dir / "output" / "external_auction_scrape" / "daily"
    autotrader_dir = root_dir / "autotrader_isolated" / "output"

    grays_links_path = scraper_dir / "all_vehicle_links.csv"
    grays_active_path = scraper_dir / "active_vehicle_details.csv"
    autotrader_path = autotrader_dir / "first_page_results.csv"
    autotrader_session_path = autotrader_dir / "storage_state.json"
    external_links_path = external_dir / "external_auction_links.csv"
    external_all_path = external_dir / "external_auction_listings_all.csv"
    external_matches_path = external_dir / "external_auction_curve_matches.csv"
    external_audit_path = external_dir / "external_auction_scrape_audit.csv"

    grays_links = _read_csv(grays_links_path)
    grays_active = _read_csv(grays_active_path)
    autotrader = _read_csv(autotrader_path)
    external_links = _read_csv(external_links_path)
    external_all = _read_csv(external_all_path)
    external_matches = _read_csv(external_matches_path)
    external_audit = _read_csv(external_audit_path)

    source_rows: list[dict[str, Any]] = []

    grays_status, grays_detail = _status_for_file(
        grays_active_path,
        rows=len(grays_active),
        now=current_time,
    )
    source_rows.append(
        _source_row(
            "Grays",
            grays_status,
            grays_detail,
            grays_active_path,
            current_time,
            discovered=len(grays_links),
            parsed=len(grays_active),
            curve_matches=_present_count(grays_active, "canonical_tag"),
            priced=_present_count(grays_active, "price"),
        )
    )

    autotrader_enabled = str(env.get("AUTOSNIPER_AUTOTRADER_SCRAPE_ENABLED", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    autotrader_status, autotrader_detail = _status_for_file(
        autotrader_path,
        rows=len(autotrader),
        now=current_time,
        enabled=autotrader_enabled,
    )
    if autotrader_enabled and not autotrader_session_path.exists():
        autotrader_status = "Failed"
        autotrader_detail = "Authenticated browser session is missing"
    source_rows.append(
        _source_row(
            "Autotrader",
            autotrader_status,
            autotrader_detail,
            autotrader_path,
            current_time,
            discovered=len(autotrader),
            parsed=len(autotrader),
            curve_matches=_present_count(autotrader, "canonical_tag"),
            priced=_present_count(autotrader, "price"),
        )
    )

    for source_name, label in (("pickles", "Pickles"), ("slattery", "Slattery"), ("manheim", "Manheim")):
        link_mask = (
            external_links.get("source", pd.Series(dtype=str)).astype(str).str.lower().eq(source_name)
            if not external_links.empty
            else pd.Series(dtype=bool)
        )
        all_mask = (
            external_all.get("source", pd.Series(dtype=str)).astype(str).str.lower().eq(source_name)
            if not external_all.empty
            else pd.Series(dtype=bool)
        )
        match_mask = (
            external_matches.get("source", pd.Series(dtype=str)).astype(str).str.lower().eq(source_name)
            if not external_matches.empty
            else pd.Series(dtype=bool)
        )
        source_links = external_links.loc[link_mask] if len(link_mask) else pd.DataFrame()
        source_details = external_all.loc[all_mask] if len(all_mask) else pd.DataFrame()
        source_matches = external_matches.loc[match_mask] if len(match_mask) else pd.DataFrame()
        source_audit = pd.DataFrame()
        if not external_audit.empty and "source" in external_audit.columns:
            audit_mask = external_audit["source"].astype(str).str.lower().eq(source_name)
            source_audit = external_audit.loc[audit_mask].tail(1)
        scrape_status = source_details.get("scrape_status", pd.Series(dtype=str)).fillna("").astype(str)
        errors = int(scrape_status.str.startswith("error:", na=False).sum())
        forbidden = int(scrape_status.str.contains("403", case=False, na=False).sum())

        status, detail = _status_for_file(
            external_all_path,
            rows=len(source_details),
            now=current_time,
        )
        if not source_audit.empty:
            audit_row = source_audit.iloc[0]
            completeness_status = _audit_text(audit_row.get("completeness_status")).lower()
            discovery_status = _audit_text(audit_row.get("discovery_status")).lower()
            audit_notes = _audit_text(audit_row.get("notes"))
            if completeness_status == "complete":
                detail = "Pagination exhausted; every selected curve candidate was detail-scraped"
                try:
                    unavailable = int(float(_audit_text(audit_row.get("selected_details_unavailable")) or "0"))
                except ValueError:
                    unavailable = 0
                if unavailable:
                    detail += f" ({unavailable} became unavailable during the crawl)"
            elif discovery_status == "blocked":
                status = "Blocked"
                detail = audit_notes or "Listing discovery is blocked"
            else:
                status = "Degraded"
                detail = audit_notes or "External auction completeness was not proved"
        elif source_name == "manheim" and forbidden:
            status = "Blocked"
            detail = "Manheim returned HTTP 403 from the VPS"
        elif errors:
            status = "Degraded"
            detail = f"{errors} detail request(s) failed"
        source_rows.append(
            _source_row(
                label,
                status,
                detail,
                external_all_path,
                current_time,
                discovered=len(source_links),
                parsed=len(source_details),
                curve_matches=len(source_matches),
                priced=_present_count(source_details, "price"),
                errors=errors + forbidden,
            )
        )

    daily_state = _read_json(root_dir / "status" / "daily_run_state.json")
    metrics = _read_json(root_dir / "status" / "metrics.json")
    health_report = _read_json(root_dir / "output" / "health" / "scraper_health.json")
    lock_path = root_dir / "logs" / "scrape.lock"
    lock_payload = _read_json(lock_path)
    lock_age = _hours_old(lock_path, current_time)
    running = bool(lock_path.exists() and lock_age is not None and lock_age < 8)

    important_statuses = {row["status"] for row in source_rows}
    if running:
        overall_status = "Running"
    elif important_statuses & {"Failed", "Blocked"}:
        overall_status = "Attention"
    elif important_statuses & {"Stale", "Degraded"}:
        overall_status = "Degraded"
    else:
        overall_status = "Operational"

    latest_error = str(daily_state.get("last_error_message") or "").strip()
    if latest_error:
        if str(daily_state.get("last_status") or "").strip().lower() == "degraded":
            latest_error = "The latest daily pipeline completed with incomplete external source coverage."
        else:
            latest_error = "The latest daily pipeline did not complete. Existing data remains available."

    return {
        "generated_at": _format_local(current_time),
        "overall_status": overall_status,
        "running_job": str(lock_payload.get("job") or "") if running else "",
        "last_daily_status": str(daily_state.get("last_status") or "unknown").replace("_", " ").title(),
        "last_daily_run": _format_local(
            daily_state.get("last_completed_utc") or daily_state.get("last_started_utc")
        ),
        "next_daily_run": _format_local(_next_daily_run(current_time)),
        "latest_automation_job": str(health_report.get("job_name") or "Unknown").replace("_", " ").title(),
        "next_hourly_run": _format_local(_next_hourly_run(current_time)),
        "last_error": latest_error,
        "active_listings": int(metrics.get("active_listings") or len(grays_active)),
        "runs_total": int(metrics.get("runs_total") or 0),
        "runs_failed": int(metrics.get("runs_failed") or 0),
        "last_duration_minutes": round(float(metrics.get("duration_sec") or 0) / 60, 1),
        "source_rows": source_rows,
    }
