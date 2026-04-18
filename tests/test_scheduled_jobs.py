from __future__ import annotations

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
