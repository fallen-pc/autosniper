from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from autotrader_isolated.poll_listing_status import (
    DEFAULT_GONE_PATTERNS,
    VERDICT_GONE,
    VERDICT_LIVE,
    VERDICT_UNKNOWN,
    absolute_listing_url,
    blank_exit_state,
    classify_response,
    listing_id,
    select_listings_to_poll,
    update_exit_state,
)


LISTING = "car/14810823/toyota/camry/vic/coburg-north/sedan"
LISTING_URL = f"https://www.autotrader.com.au/{LISTING}"


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def test_listing_id_extracts_numeric_id() -> None:
    assert listing_id(LISTING) == "14810823"
    assert listing_id(LISTING_URL) == "14810823"


def test_listing_id_blank_when_not_a_listing() -> None:
    assert listing_id("https://www.autotrader.com.au/for-sale") == ""
    assert listing_id("") == ""


def test_absolute_listing_url_handles_relative_and_absolute() -> None:
    assert absolute_listing_url(LISTING) == LISTING_URL
    assert absolute_listing_url(f"/{LISTING}") == LISTING_URL
    assert absolute_listing_url(LISTING_URL) == LISTING_URL
    assert absolute_listing_url("") == ""


# ---------------------------------------------------------------------------
# classify_response — the safety-critical part
# ---------------------------------------------------------------------------


def _classify(**kwargs):
    base = {
        "url": LISTING,
        "status_code": 200,
        "final_url": LISTING_URL,
        "html": "<html><title>2012 Toyota Camry</title></html>",
        "gone_patterns": DEFAULT_GONE_PATTERNS,
    }
    base.update(kwargs)
    return classify_response(**base)


def test_live_listing_classified_live() -> None:
    verdict, reason = _classify()
    assert verdict == VERDICT_LIVE
    assert reason == "listing_id_present"


def test_404_and_410_are_definitive_gone() -> None:
    assert _classify(status_code=404, html="")[0] == VERDICT_GONE
    assert _classify(status_code=410, html="")[0] == VERDICT_GONE


def test_redirect_off_listing_is_gone() -> None:
    verdict, reason = _classify(final_url="https://www.autotrader.com.au/for-sale")
    assert verdict == VERDICT_GONE
    assert reason == "redirected_off_listing"


def test_redirect_to_a_different_listing_is_gone() -> None:
    verdict, reason = _classify(
        final_url="https://www.autotrader.com.au/car/99999999/toyota/corolla/vic/x/sedan"
    )
    assert verdict == VERDICT_GONE
    assert reason == "redirected_to_other_listing"


def test_gone_content_pattern_detected() -> None:
    verdict, reason = _classify(html="<html>This vehicle is no longer available.</html>")
    assert verdict == VERDICT_GONE
    assert reason.startswith("content:")


def test_gone_pattern_matching_is_case_insensitive() -> None:
    assert _classify(html="<h1>NO LONGER AVAILABLE</h1>")[0] == VERDICT_GONE


def test_custom_gone_patterns_are_honoured() -> None:
    verdict, _ = _classify(html="<p>vehicle withdrawn by seller</p>",
                           gone_patterns=("vehicle withdrawn",))
    assert verdict == VERDICT_GONE


# The following must NEVER produce `gone` — that is the whole point of the module.


def test_blocked_and_rate_limited_are_unknown_not_gone() -> None:
    for status in (401, 403, 407, 429):
        verdict, reason = _classify(status_code=status, html="")
        assert verdict == VERDICT_UNKNOWN, f"status {status} must not imply gone"
        assert reason == f"http_{status}"


def test_server_errors_are_unknown_not_gone() -> None:
    for status in (500, 502, 503, 504):
        assert _classify(status_code=status, html="")[0] == VERDICT_UNKNOWN


def test_request_error_is_unknown() -> None:
    verdict, reason = _classify(error="ConnectTimeout: timed out")
    assert verdict == VERDICT_UNKNOWN
    assert reason.startswith("request_error:")


def test_missing_status_is_unknown() -> None:
    assert _classify(status_code=None)[0] == VERDICT_UNKNOWN


def test_indeterminate_200_is_unknown_not_gone() -> None:
    # 200, no redirect information, no pattern hit -> we genuinely cannot tell.
    verdict, reason = _classify(url="not-a-listing-path", final_url="", html="<html></html>")
    assert verdict == VERDICT_UNKNOWN
    assert reason == "indeterminate_200"


# ---------------------------------------------------------------------------
# update_exit_state
# ---------------------------------------------------------------------------


def _fold(row, verdict, ts, threshold=2, price=""):
    return update_exit_state(
        row,
        verdict=verdict,
        reason="test",
        http_status=200,
        poll_ts=ts,
        confirm_threshold=threshold,
        known_price=price,
    )


def test_single_gone_does_not_confirm_exit() -> None:
    row = _fold(blank_exit_state(LISTING), VERDICT_GONE, "2026-07-28T00:00:00+00:00")
    assert row["consecutive_gone"] == 1
    assert row["confirmed_gone_date"] == ""


def test_two_consecutive_gone_confirms_exit_and_captures_price() -> None:
    row = blank_exit_state(LISTING)
    row = _fold(row, VERDICT_GONE, "2026-07-28T00:00:00+00:00", price=13990)
    row = _fold(row, VERDICT_GONE, "2026-07-29T00:00:00+00:00", price=13990)
    assert row["consecutive_gone"] == 2
    assert row["confirmed_gone_date"] == "2026-07-29T00:00:00+00:00"
    assert row["exit_price"] == 13990


def test_live_resets_the_gone_streak() -> None:
    row = blank_exit_state(LISTING)
    row = _fold(row, VERDICT_GONE, "2026-07-28T00:00:00+00:00")
    row = _fold(row, VERDICT_LIVE, "2026-07-29T00:00:00+00:00")
    assert row["consecutive_gone"] == 0
    assert row["last_live_date"] == "2026-07-29T00:00:00+00:00"


def test_relisted_listing_clears_a_confirmed_exit() -> None:
    row = blank_exit_state(LISTING)
    row = _fold(row, VERDICT_GONE, "2026-07-28T00:00:00+00:00", price=13990)
    row = _fold(row, VERDICT_GONE, "2026-07-29T00:00:00+00:00", price=13990)
    assert row["confirmed_gone_date"]
    row = _fold(row, VERDICT_LIVE, "2026-07-30T00:00:00+00:00")
    assert row["confirmed_gone_date"] == ""
    assert row["exit_price"] == ""


def test_unknown_does_not_advance_or_reset_the_gone_streak() -> None:
    row = blank_exit_state(LISTING)
    row = _fold(row, VERDICT_GONE, "2026-07-28T00:00:00+00:00")
    row = _fold(row, VERDICT_UNKNOWN, "2026-07-29T00:00:00+00:00")
    assert row["consecutive_gone"] == 1
    assert row["confirmed_gone_date"] == ""
    assert row["unknown_streak"] == 1


def test_unknown_alone_never_confirms_an_exit() -> None:
    row = blank_exit_state(LISTING)
    for day in range(10):
        row = _fold(row, VERDICT_UNKNOWN, f"2026-07-{10+day:02d}T00:00:00+00:00")
    assert row["confirmed_gone_date"] == ""
    assert row["consecutive_gone"] == 0


def test_poll_count_and_first_polled_tracked() -> None:
    row = blank_exit_state(LISTING)
    row = _fold(row, VERDICT_LIVE, "2026-07-28T00:00:00+00:00")
    row = _fold(row, VERDICT_LIVE, "2026-07-29T00:00:00+00:00")
    assert row["poll_count"] == 2
    assert row["first_polled"] == "2026-07-28T00:00:00+00:00"
    assert row["last_polled"] == "2026-07-29T00:00:00+00:00"


def test_confirm_threshold_of_three_requires_three() -> None:
    row = blank_exit_state(LISTING)
    for day, expected in ((1, ""), (2, ""), (3, "confirmed")):
        row = _fold(row, VERDICT_GONE, f"2026-07-0{day}T00:00:00+00:00", threshold=3)
        if expected:
            assert row["confirmed_gone_date"] == "2026-07-03T00:00:00+00:00"
        else:
            assert row["confirmed_gone_date"] == ""


# ---------------------------------------------------------------------------
# select_listings_to_poll
# ---------------------------------------------------------------------------


def _state(urls):
    return pd.DataFrame({"url": urls})


def test_selects_all_when_nothing_tracked_yet() -> None:
    picked = select_listings_to_poll(_state(["a", "b", "c"]), pd.DataFrame())
    assert sorted(picked) == ["a", "b", "c"]


def test_empty_state_returns_nothing() -> None:
    assert select_listings_to_poll(pd.DataFrame(), pd.DataFrame()) == []


def test_confirmed_exits_are_skipped_by_default() -> None:
    exit_df = pd.DataFrame(
        [
            {"url": "a", "last_polled": "", "confirmed_gone_date": "2026-07-01T00:00:00+00:00"},
            {"url": "b", "last_polled": "", "confirmed_gone_date": ""},
        ]
    )
    picked = select_listings_to_poll(_state(["a", "b"]), exit_df)
    assert picked == ["b"]


def test_recheck_confirmed_includes_them() -> None:
    exit_df = pd.DataFrame(
        [{"url": "a", "last_polled": "", "confirmed_gone_date": "2026-07-01T00:00:00+00:00"}]
    )
    picked = select_listings_to_poll(_state(["a"]), exit_df, recheck_confirmed=True)
    assert picked == ["a"]


def test_recently_polled_listings_are_skipped() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    exit_df = pd.DataFrame(
        [
            {"url": "recent", "last_polled": (now - timedelta(hours=2)).isoformat(),
             "confirmed_gone_date": ""},
            {"url": "stale", "last_polled": (now - timedelta(hours=48)).isoformat(),
             "confirmed_gone_date": ""},
        ]
    )
    picked = select_listings_to_poll(
        _state(["recent", "stale"]), exit_df, min_hours_between_polls=12.0, now=now
    )
    assert picked == ["stale"]


def test_never_polled_sorts_before_previously_polled() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    exit_df = pd.DataFrame(
        [{"url": "old", "last_polled": (now - timedelta(hours=48)).isoformat(),
          "confirmed_gone_date": ""}]
    )
    picked = select_listings_to_poll(_state(["old", "fresh"]), exit_df, now=now)
    assert picked[0] == "fresh"


def test_max_listings_caps_the_batch() -> None:
    picked = select_listings_to_poll(_state(list("abcdef")), pd.DataFrame(), max_listings=2)
    assert len(picked) == 2


def test_tagged_only_restricts_to_tagged_urls() -> None:
    picked = select_listings_to_poll(
        _state(["a", "b", "c"]), pd.DataFrame(), tagged_urls={"b"}
    )
    assert picked == ["b"]


def test_duplicate_urls_are_collapsed() -> None:
    picked = select_listings_to_poll(_state(["a", "a", "b"]), pd.DataFrame())
    assert sorted(picked) == ["a", "b"]


def test_blank_urls_are_dropped() -> None:
    picked = select_listings_to_poll(_state(["a", "", "  "]), pd.DataFrame())
    assert picked == ["a"]
