from __future__ import annotations

import pandas as pd

from scripts.build_retail_exit_ledger import (
    LEDGER_COLUMNS,
    build_ledger,
    confirmed_exits,
    price_trajectory,
)


URL_A = "car/111/toyota/camry/vic/x/sedan"
URL_B = "car/222/ford/ranger/vic/y/dual-cab"
URL_C = "car/333/mazda/cx-5/vic/z/suv"


def _exit_state(rows):
    return pd.DataFrame(rows)


def _listing_state(rows):
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# confirmed_exits
# ---------------------------------------------------------------------------


def test_only_confirmed_rows_are_kept() -> None:
    frame = _exit_state(
        [
            {"url": URL_A, "confirmed_gone_date": "2026-07-28T00:00:00+00:00"},
            {"url": URL_B, "confirmed_gone_date": ""},
            {"url": URL_C, "confirmed_gone_date": None},
        ]
    )
    assert list(confirmed_exits(frame)["url"]) == [URL_A]


def test_nan_like_confirmation_strings_are_not_confirmations() -> None:
    frame = _exit_state(
        [
            {"url": URL_A, "confirmed_gone_date": "nan"},
            {"url": URL_B, "confirmed_gone_date": "NaT"},
            {"url": URL_C, "confirmed_gone_date": "None"},
        ]
    )
    assert confirmed_exits(frame).empty


def test_empty_exit_state_yields_no_confirmations() -> None:
    assert confirmed_exits(pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# price_trajectory
# ---------------------------------------------------------------------------


def test_initial_price_is_the_earliest_priced_event() -> None:
    history = pd.DataFrame(
        [
            {"url": URL_A, "event_date": "2026-01-02", "event": "listed", "price": 25000},
            {"url": URL_A, "event_date": "2026-02-01", "event": "price_change", "price": 23000},
            {"url": URL_A, "event_date": "2026-03-01", "event": "price_change", "price": 22000},
        ]
    )
    traj = price_trajectory(history, {URL_A}).set_index("url")
    assert traj.loc[URL_A, "initial_asking_price"] == 25000
    assert traj.loc[URL_A, "price_change_count"] == 2


def test_events_out_of_order_still_pick_the_earliest_price() -> None:
    history = pd.DataFrame(
        [
            {"url": URL_A, "event_date": "2026-03-01", "event": "price_change", "price": 22000},
            {"url": URL_A, "event_date": "2026-01-02", "event": "listed", "price": 25000},
        ]
    )
    traj = price_trajectory(history, {URL_A}).set_index("url")
    assert traj.loc[URL_A, "initial_asking_price"] == 25000


def test_zero_and_missing_prices_are_ignored_for_initial() -> None:
    history = pd.DataFrame(
        [
            {"url": URL_A, "event_date": "2026-01-01", "event": "listed", "price": 0},
            {"url": URL_A, "event_date": "2026-01-02", "event": "price_change", "price": None},
            {"url": URL_A, "event_date": "2026-01-03", "event": "price_change", "price": 19000},
        ]
    )
    traj = price_trajectory(history, {URL_A}).set_index("url")
    assert traj.loc[URL_A, "initial_asking_price"] == 19000


def test_trajectory_ignores_urls_outside_the_requested_set() -> None:
    history = pd.DataFrame(
        [
            {"url": URL_A, "event_date": "2026-01-01", "event": "listed", "price": 1000},
            {"url": URL_B, "event_date": "2026-01-01", "event": "listed", "price": 2000},
        ]
    )
    assert list(price_trajectory(history, {URL_A})["url"]) == [URL_A]


def test_empty_history_returns_empty_frame() -> None:
    assert price_trajectory(pd.DataFrame(), {URL_A}).empty


# ---------------------------------------------------------------------------
# build_ledger
# ---------------------------------------------------------------------------


def _build(exit_rows, state_rows, history=None, tagged=None):
    return build_ledger(
        _exit_state(exit_rows),
        _listing_state(state_rows),
        history if history is not None else pd.DataFrame(),
        tagged,
        None,
    )


def test_ledger_has_the_declared_columns() -> None:
    ledger = _build(
        [{"url": URL_A, "confirmed_gone_date": "2026-07-28", "last_reason": "redirect_removed_flag",
          "exit_price": 25000}],
        [{"url": URL_A, "first_seen": "2026-01-01", "last_seen": "2026-03-01",
          "last_price": 25000, "make": "Toyota"}],
    )
    assert list(ledger.columns) == LEDGER_COLUMNS


def test_unconfirmed_exits_never_reach_the_ledger() -> None:
    ledger = _build(
        [{"url": URL_A, "confirmed_gone_date": "", "exit_price": 25000}],
        [{"url": URL_A, "last_price": 25000}],
    )
    assert ledger.empty


def test_exit_price_is_preferred_over_last_price() -> None:
    ledger = _build(
        [{"url": URL_A, "confirmed_gone_date": "2026-07-28", "exit_price": 23000}],
        [{"url": URL_A, "last_price": 25000}],
    )
    assert ledger.iloc[0]["final_asking_price"] == 23000
    assert ledger.iloc[0]["price_basis"] == "exit_price"


def test_falls_back_to_last_price_when_exit_price_missing() -> None:
    ledger = _build(
        [{"url": URL_A, "confirmed_gone_date": "2026-07-28", "exit_price": None}],
        [{"url": URL_A, "last_price": 25000}],
    )
    assert ledger.iloc[0]["final_asking_price"] == 25000
    assert ledger.iloc[0]["price_basis"] == "last_price"


def test_days_on_market_computed_from_listing_dates() -> None:
    ledger = _build(
        [{"url": URL_A, "confirmed_gone_date": "2026-07-28", "exit_price": 25000}],
        [{"url": URL_A, "first_seen": "2026-01-01T00:00:00", "last_seen": "2026-01-31T00:00:00",
          "last_price": 25000}],
    )
    assert ledger.iloc[0]["days_on_market"] == 30.0


def test_reduction_and_pct_computed_from_trajectory() -> None:
    history = pd.DataFrame(
        [
            {"url": URL_A, "event_date": "2026-01-01", "event": "listed", "price": 30000},
            {"url": URL_A, "event_date": "2026-02-01", "event": "price_change", "price": 27000},
        ]
    )
    ledger = _build(
        [{"url": URL_A, "confirmed_gone_date": "2026-07-28", "exit_price": 27000}],
        [{"url": URL_A, "last_price": 27000}],
        history=history,
    )
    row = ledger.iloc[0]
    assert row["initial_asking_price"] == 30000
    assert row["total_reduction"] == 3000
    assert row["reduction_pct"] == 10.0
    assert row["price_change_count"] == 1


def test_listing_with_no_price_cut_has_zero_reduction() -> None:
    history = pd.DataFrame(
        [{"url": URL_A, "event_date": "2026-01-01", "event": "listed", "price": 20000}]
    )
    ledger = _build(
        [{"url": URL_A, "confirmed_gone_date": "2026-07-28", "exit_price": 20000}],
        [{"url": URL_A, "last_price": 20000}],
        history=history,
    )
    assert ledger.iloc[0]["total_reduction"] == 0
    assert ledger.iloc[0]["price_change_count"] == 0


def test_spec_columns_carried_across_from_listing_state() -> None:
    ledger = _build(
        [{"url": URL_A, "confirmed_gone_date": "2026-07-28", "exit_price": 25000}],
        [{"url": URL_A, "last_price": 25000, "year": 2018, "make": "Toyota",
          "model": "Camry", "odometer": 90000, "transmission": "Automatic"}],
    )
    row = ledger.iloc[0]
    assert row["make"] == "Toyota"
    assert row["model"] == "Camry"
    assert row["odometer"] == 90000


def test_canonical_tag_joined_from_tagged_feed() -> None:
    tagged = pd.DataFrame([{"url": URL_A, "canonical_tag": "toyota_camry_auto_petrol_sedan"}])
    ledger = _build(
        [{"url": URL_A, "confirmed_gone_date": "2026-07-28", "exit_price": 25000}],
        [{"url": URL_A, "last_price": 25000}],
        tagged=tagged,
    )
    assert ledger.iloc[0]["canonical_tag"] == "toyota_camry_auto_petrol_sedan"


def test_untagged_listing_still_produces_a_row() -> None:
    ledger = _build(
        [{"url": URL_A, "confirmed_gone_date": "2026-07-28", "exit_price": 25000}],
        [{"url": URL_A, "last_price": 25000}],
        tagged=pd.DataFrame([{"url": URL_B, "canonical_tag": "other"}]),
    )
    assert len(ledger) == 1
    assert ledger.iloc[0]["curve_tag"] == ""


def test_multiple_confirmed_exits_all_appear() -> None:
    ledger = _build(
        [
            {"url": URL_A, "confirmed_gone_date": "2026-07-28", "exit_price": 25000},
            {"url": URL_B, "confirmed_gone_date": "2026-07-28", "exit_price": 40000},
        ],
        [
            {"url": URL_A, "last_price": 25000},
            {"url": URL_B, "last_price": 40000},
        ],
    )
    assert sorted(ledger["url"]) == sorted([URL_A, URL_B])


def test_exit_reason_is_preserved_for_auditing() -> None:
    ledger = _build(
        [{"url": URL_A, "confirmed_gone_date": "2026-07-28",
          "last_reason": "redirect_removed_flag", "exit_price": 25000}],
        [{"url": URL_A, "last_price": 25000}],
    )
    assert ledger.iloc[0]["exit_reason"] == "redirect_removed_flag"
