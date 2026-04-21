from __future__ import annotations

import pandas as pd

import scripts.update_bids as update_bids


def test_reconcile_state_active_queue_demotes_stale_active_rows() -> None:
    state_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/keep-active",
                "state": "active",
                "time_remaining": "2h",
                "last_evidence": "live",
            },
            {
                "url": "https://example.com/lot/drop-from-queue",
                "state": "active",
                "time_remaining": "1h",
                "last_evidence": "live",
            },
            {
                "url": "https://example.com/lot/already-sold",
                "state": "sold",
                "time_remaining": "closed",
                "last_evidence": "sold",
            },
        ]
    )

    out, reconciled = update_bids.reconcile_state_active_queue(
        state_df,
        queue_urls={"https://example.com/lot/keep-active"},
    )

    assert reconciled == 1

    active_row = out.loc[out["url"] == "https://example.com/lot/keep-active"].iloc[0]
    stale_row = out.loc[out["url"] == "https://example.com/lot/drop-from-queue"].iloc[0]
    sold_row = out.loc[out["url"] == "https://example.com/lot/already-sold"].iloc[0]

    assert active_row["state"] == "active"
    assert stale_row["state"] == "static_parsed"
    assert stale_row["time_remaining"] == ""
    assert stale_row["last_evidence"] == "removed_from_active_queue"
    assert sold_row["state"] == "sold"


def test_reconcile_state_active_queue_ignores_empty_queue() -> None:
    state_df = pd.DataFrame(
        [
            {"url": "https://example.com/lot/1", "state": "active"},
        ]
    )

    out, reconciled = update_bids.reconcile_state_active_queue(state_df, queue_urls=set())

    assert reconciled == 0
    assert out.loc[0, "state"] == "active"
