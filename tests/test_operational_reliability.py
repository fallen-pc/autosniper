from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from scripts import atomic_csv
from shared import canonical_tagging
from shared.audit import append_audit_snapshot
from shared.csv_utils import count_csv_records


def test_count_csv_records_handles_embedded_newlines(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    pd.DataFrame(
        [
            {"url": "one", "condition": "first line\nsecond line"},
            {"url": "two", "condition": "single line"},
        ]
    ).to_csv(path, index=False)

    assert count_csv_records(path) == 2


def test_atomic_replace_retries_transient_windows_lock(monkeypatch, tmp_path: Path) -> None:
    destination = tmp_path / "rows.csv"
    real_replace = atomic_csv.os.replace
    attempts = 0

    def flaky_replace(source: Path, target: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("temporary Windows file lock")
        real_replace(source, target)

    monkeypatch.setattr(atomic_csv.os, "replace", flaky_replace)
    monkeypatch.setattr(atomic_csv.time, "sleep", lambda _seconds: None)

    atomic_csv.write_dataframe_csv_atomic(pd.DataFrame([{"value": 1}]), destination, index=False)

    assert attempts == 3
    assert pd.read_csv(destination).to_dict(orient="records") == [{"value": 1}]


def test_concurrent_atomic_appends_preserve_both_writers(tmp_path: Path) -> None:
    destination = tmp_path / "rows.csv"

    def append(value: int) -> None:
        atomic_csv.append_dataframe_csv_atomic(
            pd.DataFrame([{"value": value}]),
            destination,
            index=False,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(append, [1, 2]))

    assert sorted(pd.read_csv(destination)["value"].tolist()) == [1, 2]


def test_stale_csv_lock_requires_dead_owner_and_cleanup_checks_identity(
    monkeypatch, tmp_path: Path
) -> None:
    lock_path = tmp_path / ".rows.csv.lock"
    lock_path.write_text(f"pid={atomic_csv.os.getpid()}\n", encoding="ascii")
    stale_time = atomic_csv.time.time() - atomic_csv.LOCK_STALE_SECONDS - 1
    atomic_csv.os.utime(lock_path, (stale_time, stale_time))

    assert atomic_csv._can_reclaim_stale_lock(lock_path) is False
    monkeypatch.setattr(atomic_csv, "_process_is_running", lambda _pid: False)
    assert atomic_csv._can_reclaim_stale_lock(lock_path) is True

    owned_path = tmp_path / "owned.lock"
    replacement_path = tmp_path / "replacement.lock"
    owned_path.write_text("owned", encoding="ascii")
    replacement_path.write_text("replacement", encoding="ascii")
    descriptor = atomic_csv.os.open(owned_path, atomic_csv.os.O_RDONLY)
    try:
        assert atomic_csv._lock_matches_descriptor(owned_path, descriptor) is True
        assert atomic_csv._lock_matches_descriptor(replacement_path, descriptor) is False
    finally:
        atomic_csv.os.close(descriptor)


def test_audit_snapshot_is_bounded_to_latest_copy(tmp_path: Path) -> None:
    target = tmp_path / "restricted.csv"

    audit_path = append_audit_snapshot(pd.DataFrame([{"value": 1}]), target)
    append_audit_snapshot(pd.DataFrame([{"value": 2}]), target)

    assert audit_path == tmp_path / "audit" / "restricted_audit_latest.csv"
    latest = pd.read_csv(audit_path)
    assert latest["value"].tolist() == [2]
    assert len(latest) == 1


def test_canonical_tag_log_is_latest_deduplicated_snapshot(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "canonical_tagging_log_latest.csv"
    monkeypatch.setattr(canonical_tagging, "TAG_LOG_PATH", log_path)
    duplicate = {
        "timestamp": "2026-07-20T00:00:00+00:00",
        "source": "active",
        "url": "https://example.test/one",
        "reason_code": "[AMBIG_BADGE]",
        "field_snapshot": "{}",
    }

    canonical_tagging._append_tag_log([duplicate, duplicate])
    deduplicated = pd.read_csv(log_path)
    assert len(deduplicated) == 1
    canonical_tagging._append_tag_log([])

    latest = pd.read_csv(log_path)
    assert latest.empty
    assert latest.columns.tolist() == [
        "timestamp",
        "source",
        "url",
        "reason_code",
        "field_snapshot",
    ]
