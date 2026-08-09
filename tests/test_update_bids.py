from __future__ import annotations

import pandas as pd
from bs4 import BeautifulSoup

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


def test_state_observation_does_not_treat_visible_price_as_final_sale_price() -> None:
    row = pd.Series(
        {
            "url": "https://example.com/lot/camry",
            "status": "Sold",
            "price": "209",
            "bids": "7",
            "time_remaining_or_date_sold": "2026-05-01",
        }
    )

    obs = update_bids._state_observation_from_row(
        row,
        run_id="test-run",
        observed_at="2026-05-05T00:00:00+00:00",
        evidence="visible_price_and_bids_not_final_sale",
    )

    assert obs.current_price == "209"
    assert obs.final_sale_price == ""
    assert obs.has_sale_price is False


def test_extract_bid_info_marks_sold_for_heading_as_final_sale_price() -> None:
    soup = BeautifulSoup(
        """
        <div class="dls-heading-3 currentbid_price">
            Sold for <span itemprop="price">$12,101</span>
        </div>
        <abbr class="endtime" title="2026-04-06T20:00:00+10:00">06 April 2026 20:00 AEST</abbr>
        <a>141 bids</a>
        """,
        "html.parser",
    )

    (
        price,
        bids,
        time_remaining,
        date_sold,
        is_referred,
        is_active,
        final_sale_price,
        sale_price_source,
    ) = update_bids.extract_bid_info(soup)

    assert price == "12101"
    assert bids == "141"
    assert time_remaining is None
    assert date_sold == "06 April 2026 20:00 AEST"
    assert is_referred is False
    assert is_active is False
    assert final_sale_price == "12101"
    assert sale_price_source == "sold_for_heading"
