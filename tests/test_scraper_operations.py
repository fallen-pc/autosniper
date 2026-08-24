from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from shared.scraper_operations import build_scraper_operations_snapshot


NOW = datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_runtime(root: Path) -> None:
    scraper_dir = root / "CSV_data" / "scrapers"
    _write_csv(scraper_dir / "all_vehicle_links.csv", [{"url": "g1"}, {"url": "g2"}])
    _write_csv(
        scraper_dir / "active_vehicle_details.csv",
        [{"url": "g1", "canonical_tag": "toyota_test", "price": 5000}],
    )
    _write_csv(scraper_dir / "sold_cars.csv", [{"url": "s1", "price": 4000}])

    autotrader_dir = root / "autotrader_isolated" / "output"
    _write_csv(
        autotrader_dir / "first_page_results.csv",
        [{"url": "a1", "canonical_tag": "toyota_test", "price": 9000}],
    )
    (autotrader_dir / "storage_state.json").write_text("{}", encoding="utf-8")

    external_dir = root / "output" / "external_auction_scrape" / "daily"
    _write_csv(
        external_dir / "external_auction_links.csv",
        [
            {"source": "pickles", "url": "p1"},
            {"source": "slattery", "url": "s1"},
        ],
    )
    _write_csv(
        external_dir / "external_auction_listings_all.csv",
        [
            {"source": "pickles", "url": "p1", "price": 6000, "scrape_status": "parsed_http_200"},
            {"source": "slattery", "url": "s1", "price": "", "scrape_status": "parsed_http_200"},
            {"source": "manheim", "url": "m1", "price": "", "scrape_status": "parsed_http_403"},
        ],
    )
    _write_csv(
        external_dir / "external_auction_curve_matches.csv",
        [{"source": "pickles", "url": "p1"}],
    )
    _write_csv(
        external_dir / "external_auction_scrape_audit.csv",
        [
            {
                "source": "pickles",
                "discovery_status": "complete",
                "completeness_status": "complete",
                "selected_details_unavailable": 1,
                "notes": "",
            },
            {
                "source": "slattery",
                "discovery_status": "complete",
                "completeness_status": "complete",
                "notes": "",
            },
            {
                "source": "manheim",
                "discovery_status": "blocked",
                "completeness_status": "incomplete",
                "notes": "listing discovery blocked by HTTP access response",
            },
        ],
    )

    status_dir = root / "status"
    status_dir.mkdir(parents=True)
    (status_dir / "daily_run_state.json").write_text(
        json.dumps(
            {
                "last_status": "success",
                "last_completed_utc": "2026-07-28T23:30:00Z",
                "last_error_message": "",
            }
        ),
        encoding="utf-8",
    )
    (status_dir / "metrics.json").write_text(
        json.dumps({"active_listings": 1, "runs_total": 10, "runs_failed": 1, "duration_sec": 600}),
        encoding="utf-8",
    )

    timestamp = NOW.timestamp()
    for path in root.rglob("*.csv"):
        path.touch()
        path.chmod(0o644)
        import os

        os.utime(path, (timestamp, timestamp))


def test_snapshot_reports_healthy_active_sources(tmp_path: Path) -> None:
    _write_runtime(tmp_path)

    snapshot = build_scraper_operations_snapshot(
        root_dir=tmp_path,
        now=NOW,
        environment={"AUTOSNIPER_AUTOTRADER_SCRAPE_ENABLED": "1"},
    )

    by_source = {row["source"]: row for row in snapshot["source_rows"]}
    assert snapshot["overall_status"] == "Operational"
    assert snapshot["last_daily_status"] == "Success"
    assert snapshot["next_hourly_run"] == "29 Jul 2026, 10:13 AM"
    assert by_source["Grays"]["status"] == "Healthy"
    assert by_source["Autotrader"]["status"] == "Healthy"
    assert by_source["Pickles"]["priced"] == 1
    assert "every selected curve candidate" in by_source["Pickles"]["detail"]
    assert "1 became unavailable" in by_source["Pickles"]["detail"]
    assert "Manheim" not in by_source


def test_snapshot_surfaces_disabled_autotrader(tmp_path: Path) -> None:
    _write_runtime(tmp_path)

    snapshot = build_scraper_operations_snapshot(
        root_dir=tmp_path,
        now=NOW,
        environment={"AUTOSNIPER_AUTOTRADER_SCRAPE_ENABLED": "0"},
    )

    by_source = {row["source"]: row for row in snapshot["source_rows"]}
    assert by_source["Autotrader"]["status"] == "Disabled"
    assert snapshot["overall_status"] == "Operational"


def test_snapshot_sanitizes_daily_error_and_marks_running_lock(tmp_path: Path) -> None:
    _write_runtime(tmp_path)
    state_path = tmp_path / "status" / "daily_run_state.json"
    state_path.write_text(
        json.dumps(
            {
                "last_status": "failed",
                "last_started_utc": "2026-07-28T23:00:00Z",
                "last_error_message": "secret internal traceback",
            }
        ),
        encoding="utf-8",
    )
    lock_path = tmp_path / "logs" / "scrape.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(json.dumps({"job": "daily"}), encoding="utf-8")
    import os

    os.utime(lock_path, (NOW.timestamp(), NOW.timestamp()))

    snapshot = build_scraper_operations_snapshot(root_dir=tmp_path, now=NOW)

    assert snapshot["overall_status"] == "Running"
    assert snapshot["running_job"] == "daily"
    assert "traceback" not in snapshot["last_error"]
