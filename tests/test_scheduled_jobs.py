from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timezone

import pandas as pd

import scripts.scheduled_jobs as scheduled_jobs


def test_hourly_monitor_updates_only_ai_analysis_scope(monkeypatch) -> None:
    ai_scope = pd.DataFrame(
        [
            {"url": "https://example.com/lot/current-viable-1", "price": "$10", "bids": "1"},
            {"url": "https://example.com/lot/current-viable-2", "price": "$20", "bids": "2"},
        ]
    )
    captured_urls: list[list[str]] = []

    monkeypatch.setattr(scheduled_jobs, "load_ai_analysis_active_df", lambda: ai_scope)
    monkeypatch.setattr(
        scheduled_jobs,
        "_run_update_bids",
        lambda urls, *, skip_master=True: captured_urls.append(list(urls)),
    )
    monkeypatch.setattr(scheduled_jobs.update_master, "update_master_database", lambda: None)
    monkeypatch.setattr(
        scheduled_jobs,
        "diff_price_changed_listing_urls",
        lambda before_df, after_df: {"https://example.com/lot/current-viable-1"},
    )
    monkeypatch.setattr(
        scheduled_jobs,
        "revalue_active_listings",
        lambda **kwargs: {"evaluated": 1, "urls": list(kwargs.get("target_urls", []))},
    )

    scheduled_jobs.run_hourly_monitor()

    assert captured_urls == [
        [
            "https://example.com/lot/current-viable-1",
            "https://example.com/lot/current-viable-2",
        ]
    ]


def test_hourly_monitor_revalues_price_changed_urls(monkeypatch) -> None:
    ai_scope = pd.DataFrame(
        [
            {"url": "https://example.com/lot/current-viable-1", "price": "$10"},
        ]
    )
    captured_kwargs: list[dict[str, object]] = []

    monkeypatch.setattr(scheduled_jobs, "load_ai_analysis_active_df", lambda: ai_scope)
    monkeypatch.setattr(scheduled_jobs, "_run_update_bids", lambda urls, *, skip_master=True: None)
    monkeypatch.setattr(scheduled_jobs.update_master, "update_master_database", lambda: None)
    monkeypatch.setattr(
        scheduled_jobs,
        "diff_price_changed_listing_urls",
        lambda before_df, after_df: {"https://example.com/lot/current-viable-1"},
    )
    monkeypatch.setattr(
        scheduled_jobs,
        "revalue_active_listings",
        lambda **kwargs: captured_kwargs.append(dict(kwargs)) or {"evaluated": 1, "urls": []},
    )

    scheduled_jobs.run_hourly_monitor()

    assert captured_kwargs == [
        {
            "target_urls": {"https://example.com/lot/current-viable-1"},
            "stale_minutes": 60,
            "force_refresh": True,
        }
    ]


def test_hourly_monitor_rematerializes_active_view_after_bid_update(monkeypatch) -> None:
    ai_scope = pd.DataFrame(
        [
            {"url": "https://example.com/lot/current-viable-1", "price": "$10"},
        ]
    )
    calls: list[str] = []

    monkeypatch.setattr(scheduled_jobs, "load_ai_analysis_active_df", lambda: ai_scope)
    monkeypatch.setattr(
        scheduled_jobs,
        "_run_update_bids",
        lambda urls, *, skip_master=True: calls.append("bids"),
    )
    monkeypatch.setattr(
        scheduled_jobs.update_master,
        "update_master_database",
        lambda: calls.append("master"),
    )
    monkeypatch.setattr(
        scheduled_jobs,
        "diff_price_changed_listing_urls",
        lambda before_df, after_df: set(),
    )
    monkeypatch.setattr(
        scheduled_jobs,
        "revalue_active_listings",
        lambda **kwargs: calls.append("revalue") or {"evaluated": 0},
    )

    scheduled_jobs.run_hourly_monitor()

    assert calls == ["bids", "master", "revalue"]


def test_daily_smoke_runs_limited_pipeline(monkeypatch) -> None:
    ai_scope = pd.DataFrame(
        [
            {"url": "https://example.com/lot/current-viable-1", "price": "$10"},
            {"url": "https://example.com/lot/current-viable-2", "price": "$20"},
        ]
    )
    calls: list[tuple[str, object]] = []

    monkeypatch.setenv("AUTOSNIPER_DAILY_SMOKE_DETAIL_LIMIT", "3")
    monkeypatch.setenv("AUTOSNIPER_DAILY_SMOKE_AUTOTRADER_PAGES", "1")
    monkeypatch.setattr(
        scheduled_jobs.extract_links,
        "extract_all_vehicle_links",
        lambda **kwargs: calls.append(("links", kwargs)),
    )
    monkeypatch.setattr(
        scheduled_jobs.extract_vehicle_details,
        "main",
        lambda **kwargs: calls.append(("details", kwargs)),
    )
    monkeypatch.setattr(scheduled_jobs, "load_ai_analysis_active_df", lambda: ai_scope)
    monkeypatch.setattr(
        scheduled_jobs,
        "_run_update_bids",
        lambda urls, *, skip_master=True: calls.append(("bids", list(urls))),
    )
    monkeypatch.setattr(
        scheduled_jobs,
        "_run_autotrader_scrape",
        lambda max_pages=None: calls.append(("autotrader", max_pages)),
    )
    monkeypatch.setattr(
        scheduled_jobs.update_master,
        "update_master_database",
        lambda: calls.append(("master", None)),
    )
    monkeypatch.setattr(
        scheduled_jobs,
        "diff_price_changed_listing_urls",
        lambda before_df, after_df: {"https://example.com/lot/current-viable-2"},
    )
    monkeypatch.setattr(
        scheduled_jobs,
        "revalue_active_listings",
        lambda **kwargs: calls.append(("revalue", kwargs)) or {"evaluated": 1},
    )
    monkeypatch.setattr(
        scheduled_jobs,
        "write_governance_report_bundle",
        lambda report_dir: {
            "coverage_summary": {"missing_tags": 0},
            "monotonicity_summary": {"errors": 0, "warnings": 0},
        },
    )
    monkeypatch.setattr(
        scheduled_jobs,
        "compute_outcome_metrics",
        lambda: calls.append(("outcomes", None)),
    )

    scheduled_jobs.run_daily_smoke()

    assert calls == [
        ("links", {}),
        ("details", {"batch_size": 3, "checkpoint_every": 3}),
        (
            "bids",
            [
                "https://example.com/lot/current-viable-1",
                "https://example.com/lot/current-viable-2",
            ],
        ),
        ("autotrader", 1),
        ("master", None),
        (
            "revalue",
            {
                "target_urls": {"https://example.com/lot/current-viable-2"},
                "stale_minutes": 60,
                "force_refresh": True,
            },
        ),
        ("outcomes", None),
    ]


def test_scheduled_autotrader_uses_seed_urls_file(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []
    storage_state = tmp_path / "autotrader_isolated" / "output" / "storage_state.json"
    cookie_file = tmp_path / "autotrader_isolated" / "output" / "autotrader_cookie.txt"
    seed_urls = tmp_path / "autotrader_isolated" / "seed_urls.txt"
    storage_state.parent.mkdir(parents=True)
    seed_urls.parent.mkdir(parents=True, exist_ok=True)
    storage_state.write_text("{}", encoding="utf-8")
    cookie_file.write_text("cookie=value", encoding="utf-8")
    seed_urls.write_text(
        "https://www.autotrader.com.au/for-sale/used/toyota/vic/melbourne\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(scheduled_jobs, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(scheduled_jobs, "AUTOTRADER_SEED_URLS_PATH", seed_urls)
    monkeypatch.setattr(
        scheduled_jobs.subprocess,
        "run",
        lambda command, check: calls.append(command),
    )

    scheduled_jobs._run_autotrader_scrape(max_pages=2)

    command = calls[0]
    assert "--urls-file" in command
    assert command[command.index("--urls-file") + 1] == str(seed_urls)
    assert "--max-pages" in command
    assert command[command.index("--max-pages") + 1] == "2"


def test_runtime_backup_skips_when_backup_dir_not_configured(monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.delenv("AUTOSNIPER_BACKUP_DIR", raising=False)
    monkeypatch.setattr(scheduled_jobs.subprocess, "run", lambda command, check: calls.append(command))

    scheduled_jobs._run_runtime_backup_if_configured()

    assert calls == []


def test_runtime_backup_runs_configured_script(monkeypatch, tmp_path) -> None:
    calls: list[tuple[list[str], bool]] = []
    script_path = tmp_path / "backup_runtime_data.ps1"
    script_path.write_text("Write-Host backup", encoding="utf-8")

    monkeypatch.setenv("AUTOSNIPER_BACKUP_DIR", r"C:\Backups\AutoSniper")
    monkeypatch.delenv("AUTOSNIPER_BACKUP_INCLUDE_AUTOTRADER_SESSION", raising=False)
    monkeypatch.setattr(scheduled_jobs, "RUNTIME_BACKUP_SCRIPT", script_path)
    monkeypatch.setattr(
        scheduled_jobs.subprocess,
        "run",
        lambda command, check: calls.append((command, check)),
    )

    scheduled_jobs._run_runtime_backup_if_configured()

    assert calls == [
        (
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-BackupDir",
                r"C:\Backups\AutoSniper",
            ],
            True,
        )
    ]


def test_runtime_backup_can_include_autotrader_session(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []
    script_path = tmp_path / "backup_runtime_data.ps1"
    script_path.write_text("Write-Host backup", encoding="utf-8")

    monkeypatch.setenv("AUTOSNIPER_BACKUP_DIR", r"C:\Backups\AutoSniper")
    monkeypatch.setenv("AUTOSNIPER_BACKUP_INCLUDE_AUTOTRADER_SESSION", "1")
    monkeypatch.setattr(scheduled_jobs, "RUNTIME_BACKUP_SCRIPT", script_path)
    monkeypatch.setattr(scheduled_jobs.subprocess, "run", lambda command, check: calls.append(command))

    scheduled_jobs._run_runtime_backup_if_configured()

    assert calls[0][-1] == "-IncludeAutotraderSession"


def test_playwright_preflight_installs_missing_chromium(monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.setattr(scheduled_jobs, "PlaywrightError", RuntimeError)

    async def probe() -> None:
        calls.append("probe")
        if calls.count("probe") == 1:
            raise RuntimeError("Executable doesn't exist at chromium.exe. Please run playwright install")

    monkeypatch.setattr(scheduled_jobs, "_probe_playwright_chromium", probe)
    monkeypatch.setattr(
        scheduled_jobs.subprocess,
        "run",
        lambda command, check: calls.append(("install", command, check)),
    )

    scheduled_jobs._ensure_playwright_chromium_available()

    assert calls == [
        "probe",
        ("install", [sys.executable, "-m", "playwright", "install", "chromium"], True),
        "probe",
    ]


def test_playwright_preflight_can_fail_fast_when_auto_install_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AUTOSNIPER_PLAYWRIGHT_AUTO_INSTALL", "0")
    monkeypatch.setattr(scheduled_jobs, "PlaywrightError", RuntimeError)

    async def probe() -> None:
        raise RuntimeError("Executable doesn't exist at chromium.exe")

    monkeypatch.setattr(scheduled_jobs, "_probe_playwright_chromium", probe)

    try:
        scheduled_jobs._ensure_playwright_chromium_available()
    except RuntimeError as exc:
        assert "Playwright Chromium is missing" in str(exc)
    else:
        raise AssertionError("Expected missing Chromium to fail fast when auto-install is disabled")


def test_playwright_preflight_reports_install_failure(monkeypatch) -> None:
    monkeypatch.setattr(scheduled_jobs, "PlaywrightError", RuntimeError)

    async def probe() -> None:
        raise RuntimeError("Executable doesn't exist at chromium.exe")

    monkeypatch.setattr(scheduled_jobs, "_probe_playwright_chromium", probe)

    def fail_install(command, check):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(scheduled_jobs.subprocess, "run", fail_install)

    try:
        scheduled_jobs._ensure_playwright_chromium_available()
    except RuntimeError as exc:
        assert "automatic installation failed" in str(exc)
    else:
        raise AssertionError("Expected install failure to be reported clearly")


def test_explicit_daily_run_counts_today_even_before_schedule(monkeypatch) -> None:
    monkeypatch.setenv("AUTOSNIPER_LOCAL_TIMEZONE", "Australia/Sydney")
    monkeypatch.setenv("AUTOSNIPER_DAILY_SCHEDULE_LOCAL_TIME", "09:00")

    before_schedule_utc = datetime(2026, 4, 20, 20, 18, tzinfo=timezone.utc)

    assert scheduled_jobs._coverage_date_for_explicit_daily_run(before_schedule_utc) == date(2026, 4, 21)
    assert scheduled_jobs._latest_due_daily_date_local(before_schedule_utc) == date(2026, 4, 20)


def test_should_not_catch_up_if_metrics_already_cover_today(monkeypatch, tmp_path) -> None:
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(
        json.dumps({"last_run_utc": "2026-04-21T01:49:24.105072Z"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(scheduled_jobs, "METRICS_PATH", metrics_path)
    monkeypatch.setattr(scheduled_jobs, "DAILY_STATE_PATH", tmp_path / "daily_run_state.json")
    monkeypatch.setenv("AUTOSNIPER_LOCAL_TIMEZONE", "Australia/Sydney")
    monkeypatch.setenv("AUTOSNIPER_DAILY_SCHEDULE_LOCAL_TIME", "09:00")

    should_run, coverage_date = scheduled_jobs._should_run_missed_daily_catchup(
        now=datetime(2026, 4, 21, 3, 0, tzinfo=timezone.utc)
    )

    assert should_run is False
    assert coverage_date == date(2026, 4, 21)


def test_should_not_catch_up_if_success_state_already_covers_today(monkeypatch, tmp_path) -> None:
    daily_state_path = tmp_path / "daily_run_state.json"
    daily_state_path.write_text(
        json.dumps(
            {
                "last_status": "skipped",
                "last_coverage_date_local": "2026-04-21",
                "last_success_coverage_date_local": "2026-04-21",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(scheduled_jobs, "METRICS_PATH", tmp_path / "metrics.json")
    monkeypatch.setattr(scheduled_jobs, "DAILY_STATE_PATH", daily_state_path)
    monkeypatch.setenv("AUTOSNIPER_LOCAL_TIMEZONE", "Australia/Sydney")
    monkeypatch.setenv("AUTOSNIPER_DAILY_SCHEDULE_LOCAL_TIME", "09:00")

    should_run, coverage_date = scheduled_jobs._should_run_missed_daily_catchup(
        now=datetime(2026, 4, 21, 3, 0, tzinfo=timezone.utc)
    )

    assert should_run is False
    assert coverage_date == date(2026, 4, 21)


def test_should_catch_up_if_today_only_has_running_attempt(monkeypatch, tmp_path) -> None:
    daily_state_path = tmp_path / "daily_run_state.json"
    daily_state_path.write_text(
        json.dumps(
            {
                "last_status": "running",
                "last_coverage_date_local": "2026-04-21",
                "last_success_coverage_date_local": "2026-04-20",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(scheduled_jobs, "METRICS_PATH", tmp_path / "metrics.json")
    monkeypatch.setattr(scheduled_jobs, "DAILY_STATE_PATH", daily_state_path)
    monkeypatch.setenv("AUTOSNIPER_LOCAL_TIMEZONE", "Australia/Sydney")
    monkeypatch.setenv("AUTOSNIPER_DAILY_SCHEDULE_LOCAL_TIME", "09:00")

    should_run, coverage_date = scheduled_jobs._should_run_missed_daily_catchup(
        now=datetime(2026, 4, 21, 3, 0, tzinfo=timezone.utc)
    )

    assert should_run is True
    assert coverage_date == date(2026, 4, 21)


def test_should_not_catch_up_inside_daily_grace_window(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(scheduled_jobs, "METRICS_PATH", tmp_path / "metrics.json")
    monkeypatch.setattr(scheduled_jobs, "DAILY_STATE_PATH", tmp_path / "daily_run_state.json")
    monkeypatch.setenv("AUTOSNIPER_LOCAL_TIMEZONE", "Australia/Sydney")
    monkeypatch.setenv("AUTOSNIPER_DAILY_SCHEDULE_LOCAL_TIME", "09:00")
    monkeypatch.setenv("AUTOSNIPER_DAILY_CATCHUP_GRACE_MINUTES", "30")

    should_run, coverage_date = scheduled_jobs._should_run_missed_daily_catchup(
        now=datetime(2026, 4, 23, 23, 5, tzinfo=timezone.utc)
    )

    assert should_run is False
    assert coverage_date == date(2026, 4, 24)


def test_should_catch_up_after_daily_grace_window(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(scheduled_jobs, "METRICS_PATH", tmp_path / "metrics.json")
    monkeypatch.setattr(scheduled_jobs, "DAILY_STATE_PATH", tmp_path / "daily_run_state.json")
    monkeypatch.setenv("AUTOSNIPER_LOCAL_TIMEZONE", "Australia/Sydney")
    monkeypatch.setenv("AUTOSNIPER_DAILY_SCHEDULE_LOCAL_TIME", "09:00")
    monkeypatch.setenv("AUTOSNIPER_DAILY_CATCHUP_GRACE_MINUTES", "30")

    should_run, coverage_date = scheduled_jobs._should_run_missed_daily_catchup(
        now=datetime(2026, 4, 24, 0, 1, tzinfo=timezone.utc)
    )

    assert should_run is True
    assert coverage_date == date(2026, 4, 24)


def test_hourly_does_not_expire_active_daily_lock(monkeypatch, tmp_path) -> None:
    lock_path = tmp_path / "scrape.lock"
    lock_path.write_text(json.dumps({"job": "daily", "started_at": time.time()}), encoding="utf-8")
    three_hours_ago = time.time() - (3 * 3600)
    os.utime(lock_path, (three_hours_ago, three_hours_ago))

    monkeypatch.setattr(scheduled_jobs, "LOCK_PATH", lock_path)

    assert scheduled_jobs._acquire_lock("hourly-monitor") is False
    assert json.loads(lock_path.read_text(encoding="utf-8"))["job"] == "daily"


def test_lock_busy_daily_records_skip_without_erasing_success(monkeypatch, tmp_path) -> None:
    daily_state_path = tmp_path / "daily_run_state.json"
    daily_state_path.write_text(
        json.dumps(
            {
                "last_status": "running",
                "last_coverage_date_local": "2026-04-21",
                "last_success_utc": "2026-04-20T01:00:00Z",
                "last_success_coverage_date_local": "2026-04-20",
            }
        ),
        encoding="utf-8",
    )
    lock_path = tmp_path / "scrape.lock"
    lock_path.write_text(json.dumps({"job": "hourly-monitor", "started_at": time.time()}), encoding="utf-8")

    monkeypatch.setattr(scheduled_jobs, "DAILY_STATE_PATH", daily_state_path)
    monkeypatch.setattr(scheduled_jobs, "LOCK_PATH", lock_path)

    scheduled_jobs._run_daily_job(trigger="catchup", coverage_date_local=date(2026, 4, 21))

    state = json.loads(daily_state_path.read_text(encoding="utf-8"))
    assert state["last_status"] == "skipped"
    assert state["last_error_message"] == "Lock busy; skipped daily run."
    assert state["last_success_utc"] == "2026-04-20T01:00:00Z"
    assert state["last_success_coverage_date_local"] == "2026-04-20"


def test_main_runs_daily_catchup_before_hourly(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(sys, "argv", ["scheduled_jobs.py", "--job", "hourly-monitor"])
    monkeypatch.setattr(scheduled_jobs, "_wait_for_internet", lambda max_wait_hours: True)
    monkeypatch.setattr(
        scheduled_jobs,
        "_run_missed_daily_catchup_if_due",
        lambda trigger_job: calls.append(("catchup", trigger_job)) or True,
    )
    monkeypatch.setattr(
        scheduled_jobs,
        "run_hourly_monitor",
        lambda: calls.append(("hourly", None)),
    )

    scheduled_jobs.main()

    assert calls == [("catchup", "hourly-monitor")]
