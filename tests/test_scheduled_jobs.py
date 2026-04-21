from __future__ import annotations

import json
import sys
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
