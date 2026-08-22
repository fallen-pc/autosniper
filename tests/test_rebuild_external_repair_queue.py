from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from scripts.rebuild_external_repair_queue import rebuild_external_repair_queue, write_rebuilt_queue


def _queue_row(repair_key: str, *, url: str, source_file: str = "ACTIVE_MONITOR") -> dict[str, object]:
    return {
        "repair_key": repair_key,
        "repair_item": repair_key,
        "review_bucket": "Needs AI Analysis review",
        "status": "unclassified",
        "category": "unclassified",
        "canonical_defects": "",
        "occurrences": 1,
        "listing_count": 1,
        "source_file": source_file,
        "example_vehicles": "Demo Vehicle",
        "example_urls": url,
        "example_condition_notes": repair_key,
    }


def test_rebuild_prunes_only_stale_active_monitor_rows_with_parsed_evidence() -> None:
    pickles_url = "https://www.pickles.com.au/used/details/cars/demo/1"
    unavailable_url = "https://www.pickles.com.au/used/details/cars/demo/2"
    grays_url = "https://www.grays.com/lot/demo"
    queue_df = pd.DataFrame(
        [
            _queue_row("generic legal disclaimer", url=pickles_url),
            _queue_row("tilt tray required", url=pickles_url),
            _queue_row("manual review history", url=pickles_url, source_file="AI_ANALYSIS_LIVE"),
            _queue_row("generic legal disclaimer", url=unavailable_url),
            _queue_row("generic legal disclaimer", url=grays_url),
        ]
    )
    external_df = pd.DataFrame(
        [
            {
                "source": "pickles",
                "url": pickles_url,
                "scrape_status": "parsed_http_200",
                "general_condition": "Please note: tilt tray required for collection.",
            },
            {
                "source": "pickles",
                "url": unavailable_url,
                "scrape_status": "unavailable_redirect",
                "general_condition": "",
            },
        ]
    )

    cleaned, removed, summary = rebuild_external_repair_queue(queue_df, external_df)

    assert summary.queue_rows_before == 5
    assert summary.queue_rows_after == 4
    assert summary.parsed_urls == 1
    assert summary.candidate_rows == 2
    assert summary.removed_rows == 1
    assert removed.iloc[0]["repair_key"] == "generic legal disclaimer"
    assert set(cleaned["repair_key"]) == {
        "tilt tray required",
        "manual review history",
        "generic legal disclaimer",
    }
    assert len(cleaned[cleaned["repair_key"].eq("generic legal disclaimer")]) == 2


def test_rebuild_treats_parsed_blank_condition_as_current_empty_evidence() -> None:
    url = "https://www.pickles.com.au/used/details/cars/demo/3"
    queue_df = pd.DataFrame([_queue_row("stale metadata fragment", url=url)])
    external_df = pd.DataFrame(
        [{"source": "pickles", "url": url, "scrape_status": "parsed", "general_condition": ""}]
    )

    cleaned, removed, summary = rebuild_external_repair_queue(queue_df, external_df)

    assert cleaned.empty
    assert len(removed) == 1
    assert summary.removed_rows == 1


def test_write_rebuilt_queue_creates_prewrite_backup(tmp_path) -> None:
    queue_path = tmp_path / "repair_review_live_queue.csv"
    original = pd.DataFrame([_queue_row("stale row", url="https://example.com/old")])
    cleaned = pd.DataFrame([_queue_row("current row", url="https://example.com/current")])
    original.to_csv(queue_path, index=False)

    backup_path = write_rebuilt_queue(
        queue_path=queue_path,
        cleaned_df=cleaned,
        created_at=datetime(2026, 8, 22, 1, 2, 3, tzinfo=timezone.utc),
    )

    assert backup_path.name == "repair_review_live_queue.pre_external_rebuild_20260822T010203Z.csv"
    assert pd.read_csv(backup_path).iloc[0]["repair_key"] == "stale row"
    assert pd.read_csv(queue_path).iloc[0]["repair_key"] == "current row"
