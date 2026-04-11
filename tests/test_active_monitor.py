from __future__ import annotations

import pandas as pd

import scripts.active_monitor as active_monitor


def test_mark_dropped_coverage_urls_writes_not_covered(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(active_monitor, "upsert_manual_result_row", lambda row: captured.append(dict(row)))

    all_active_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/1",
                "canonical_tag": "demo_tag",
                "canonical_reason": "[matched]",
                "price": "$5,000",
                "bids": "3",
                "time_remaining_or_date_sold": "2h 15m",
            }
        ]
    )
    covered_active_df = pd.DataFrame(columns=all_active_df.columns)

    count = active_monitor._mark_dropped_coverage_urls(
        all_active_df,
        covered_active_df,
        {"https://example.com/lot/1"},
    )

    assert count == 1
    assert len(captured) == 1
    row = captured[0]
    assert row["computed_verdict"] == "Not Covered"
    assert row["analysis_context"] == "active"
    assert row["no_edge"] is True
    assert "no longer curve-covered" in str(row["edge_note"]).lower()


def test_mark_dropped_coverage_urls_ignores_non_targets(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(active_monitor, "upsert_manual_result_row", lambda row: captured.append(dict(row)))

    all_active_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/1",
                "canonical_tag": "demo_tag",
                "canonical_reason": "[matched]",
            }
        ]
    )
    covered_active_df = pd.DataFrame(columns=all_active_df.columns)

    count = active_monitor._mark_dropped_coverage_urls(
        all_active_df,
        covered_active_df,
        {"https://example.com/lot/other"},
    )

    assert count == 0
    assert captured == []


def test_load_ai_analysis_active_df_uses_prepared_scope(monkeypatch) -> None:
    expected_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/ai-viable",
                "curve_coverage": True,
            }
        ]
    )

    monkeypatch.setattr(
        active_monitor,
        "_prepare_active_scope",
        lambda: (expected_df, pd.DataFrame(), pd.DataFrame()),
    )

    result = active_monitor.load_ai_analysis_active_df()

    assert result is expected_df
