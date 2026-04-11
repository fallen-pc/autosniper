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
