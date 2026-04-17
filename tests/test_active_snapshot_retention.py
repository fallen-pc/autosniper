from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.active_snapshot_retention import compact_active_snapshots
from scripts.prepare_sold_training_data import merge_snapshot_features
from scripts.update_bids import select_snapshot_retention_urls


SNAPSHOT_COLUMNS = [
    "snapshot_ts",
    "url",
    "price_text",
    "price_numeric",
    "bids_numeric",
    "time_remaining_text",
    "time_remaining_hours",
    "status",
    "location",
    "location_state",
    "auction_site",
]


def _write_snapshots(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS).to_csv(path, index=False)


def test_compact_active_snapshots_keeps_latest_active_and_archives_rest(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "active_snapshots.csv"
    archive_dir = tmp_path / "archives" / "active_snapshots"
    active_url = "https://example.com/lot/active"
    sold_url = "https://example.com/lot/sold"
    _write_snapshots(
        snapshot_path,
        [
            {
                "snapshot_ts": "2026-04-18T00:00:00+00:00",
                "url": active_url,
                "price_numeric": 1000,
                "bids_numeric": 1,
                "status": "Active",
            },
            {
                "snapshot_ts": "2026-04-18T01:00:00+00:00",
                "url": active_url,
                "price_numeric": 1200,
                "bids_numeric": 2,
                "status": "Active",
            },
            {
                "snapshot_ts": "2026-04-18T02:00:00+00:00",
                "url": sold_url,
                "price_numeric": 1500,
                "bids_numeric": 3,
                "status": "Sold",
            },
        ],
    )

    result = compact_active_snapshots(
        snapshot_path=snapshot_path,
        active_urls=[active_url],
        archive_dir=archive_dir,
    )

    current = pd.read_csv(snapshot_path)
    archive = pd.read_csv(archive_dir / "active_snapshots_2026-04.csv")

    assert result.current_rows == 1
    assert result.archived_rows == 2
    assert current["url"].tolist() == [active_url]
    assert current["price_numeric"].tolist() == [1200]
    assert set(archive["price_numeric"].tolist()) == {1000, 1500}


def test_merge_snapshot_features_reads_archived_snapshots(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "active_snapshots.csv"
    archive_dir = tmp_path / "archives" / "active_snapshots"
    archive_dir.mkdir(parents=True)
    sold_url = "https://example.com/lot/sold"

    _write_snapshots(snapshot_path, [])
    _write_snapshots(
        archive_dir / "active_snapshots_2026-04.csv",
        [
            {
                "snapshot_ts": "2026-04-18T02:00:00+00:00",
                "url": sold_url,
                "price_numeric": 1500,
                "bids_numeric": 3,
                "time_remaining_hours": 1.5,
                "status": "Sold",
                "location_state": "VIC",
            }
        ],
    )
    sold_df = pd.DataFrame(
        [
            {
                "url": sold_url,
                "date_sold_parsed": pd.Timestamp("2026-04-18 03:00:00"),
            }
        ]
    )

    merged = merge_snapshot_features(sold_df, snapshot_path, archive_dir)

    assert merged["snapshot_price_numeric"].tolist() == [1500]
    assert merged["snapshot_bids_numeric"].tolist() == [3]
    assert merged["snapshot_location_state"].tolist() == ["VIC"]
    assert merged["snapshot_hours_to_close"].tolist() == [1.0]


def test_select_snapshot_retention_urls_respects_hourly_scope() -> None:
    full_active_url = "https://example.com/lot/full-active"
    hourly_active_url = "https://example.com/lot/hourly-active"
    hourly_sold_url = "https://example.com/lot/hourly-sold"
    df = pd.DataFrame(
        [
            {"url": full_active_url, "status": "Active"},
            {"url": hourly_active_url, "status": "Active"},
            {"url": hourly_sold_url, "status": "Sold"},
        ]
    )

    hourly_urls = select_snapshot_retention_urls(df, [hourly_active_url, hourly_sold_url])
    broad_urls = select_snapshot_retention_urls(df)

    assert hourly_urls == [hourly_active_url]
    assert broad_urls == [full_active_url, hourly_active_url]
