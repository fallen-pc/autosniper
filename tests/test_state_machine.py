from __future__ import annotations

import pandas as pd

from shared.schema import STATE_ACTIVE, STATE_DEAD_URL, STATE_SOLD
from shared.state_machine import ListingObservation, evaluate_transition, upsert_state_row


def test_transition_to_sold_requires_positive_evidence() -> None:
    obs = ListingObservation(
        url="https://example.com/lot/1",
        observed_at="2026-03-12T00:00:00+00:00",
        has_sale_price=True,
        evidence="final_price_present",
    )
    decision = evaluate_transition("active", obs)
    assert decision.state == STATE_SOLD
    assert decision.reason_code == "EVIDENCE_FINAL_PRICE"


def test_fetch_fail_keeps_previous_state_before_threshold() -> None:
    obs = ListingObservation(
        url="https://example.com/lot/1",
        observed_at="2026-03-12T00:00:00+00:00",
        fetch_failed=True,
        fetch_error="timeout",
    )
    decision = evaluate_transition("active", obs, previous_fetch_fail_count=1, fetch_fail_dead_threshold=3)
    assert decision.state == STATE_ACTIVE
    assert decision.fetch_fail_count == 2


def test_fetch_fail_reaches_dead_url_threshold() -> None:
    obs = ListingObservation(
        url="https://example.com/lot/1",
        observed_at="2026-03-12T00:00:00+00:00",
        fetch_failed=True,
        fetch_error="timeout",
    )
    decision = evaluate_transition("active", obs, previous_fetch_fail_count=2, fetch_fail_dead_threshold=3)
    assert decision.state == STATE_DEAD_URL


def test_upsert_state_row_updates_existing_url() -> None:
    base = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/1",
                "state": "active",
                "current_price": "5000",
                "bid_count": "2",
            }
        ]
    )
    obs = ListingObservation(
        url="https://example.com/lot/1",
        observed_at="2026-03-12T00:00:00+00:00",
        has_sale_price=True,
        current_price="6200",
        bid_count="8",
    )
    out, decision = upsert_state_row(base, obs)
    assert len(out) == 1
    assert out.iloc[0]["state"] == STATE_SOLD
    assert str(out.iloc[0]["current_price"]) == "6200"
    assert str(out.iloc[0]["bid_count"]) == "8"
    assert decision.state == STATE_SOLD
