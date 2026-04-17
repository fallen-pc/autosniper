from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.data_loader import dataset_path
else:  # pragma: no cover
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.data_loader import dataset_path


DEFAULT_SNAPSHOT_PATH = dataset_path("active_snapshots.csv")
DEFAULT_ARCHIVE_DIR = dataset_path("archives/active_snapshots")


@dataclass(frozen=True)
class SnapshotRetentionResult:
    current_rows: int
    archived_rows: int
    archive_files: tuple[Path, ...]


def _normalise_url(value: object) -> str:
    return str(value or "").strip().lower()


def _active_url_keys(active_urls: Iterable[str]) -> set[str]:
    return {key for key in (_normalise_url(url) for url in active_urls) if key}


def _load_active_urls(active_path: Path) -> list[str]:
    if not active_path.exists():
        return []
    active_df = pd.read_csv(active_path, low_memory=False)
    if "url" not in active_df.columns:
        return []
    if "status" in active_df.columns:
        status = active_df["status"].fillna("").astype(str).str.strip().str.lower()
        active_df = active_df[status.eq("active")].copy()
    return active_df["url"].dropna().astype(str).tolist()


def _archive_bucket(snapshot_ts: object) -> str:
    parsed = pd.to_datetime(pd.Series([snapshot_ts]), errors="coerce", utc=True).iloc[0]
    if pd.isna(parsed):
        return "unknown"
    return f"{parsed.year:04d}-{parsed.month:02d}"


def _append_archive_rows(rows: pd.DataFrame, archive_dir: Path) -> tuple[Path, ...]:
    if rows.empty:
        return ()

    archive_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    working = rows.copy()
    if "snapshot_ts" not in working.columns:
        working["snapshot_ts"] = ""
    working["_archive_bucket"] = working["snapshot_ts"].apply(_archive_bucket)

    for bucket, bucket_rows in working.groupby("_archive_bucket", sort=True):
        destination = archive_dir / f"active_snapshots_{bucket}.csv"
        output_rows = bucket_rows.drop(columns=["_archive_bucket"]).copy()
        if destination.exists():
            existing = pd.read_csv(destination, low_memory=False)
            output_rows = pd.concat([existing, output_rows], ignore_index=True, sort=False)
            output_rows = output_rows.drop_duplicates(keep="first")
        write_dataframe_csv_atomic(output_rows, destination, index=False)
        written.append(destination)

    return tuple(written)


def compact_active_snapshots(
    *,
    snapshot_path: Path | str = DEFAULT_SNAPSHOT_PATH,
    active_urls: Iterable[str],
    archive_dir: Path | str = DEFAULT_ARCHIVE_DIR,
) -> SnapshotRetentionResult:
    """Keep only the latest snapshot per active URL and archive the rest.

    Active snapshots are short-lived monitoring data. Older hourly rows are
    retained outside the live CSV so later training or analysis can opt into
    them without dirtying the current operational dataset.
    """

    snapshot_path = Path(snapshot_path)
    archive_dir = Path(archive_dir)
    if not snapshot_path.exists():
        return SnapshotRetentionResult(current_rows=0, archived_rows=0, archive_files=())

    snapshots = pd.read_csv(snapshot_path, low_memory=False)
    if snapshots.empty or "url" not in snapshots.columns:
        return SnapshotRetentionResult(current_rows=len(snapshots), archived_rows=0, archive_files=())

    original_columns = list(snapshots.columns)
    working = snapshots.copy()
    working["_row_order"] = range(len(working))
    working["_url_key"] = working["url"].apply(_normalise_url)
    if "snapshot_ts" in working.columns:
        working["_snapshot_ts_sort"] = pd.to_datetime(
            working["snapshot_ts"],
            errors="coerce",
            utc=True,
        )
    else:
        working["_snapshot_ts_sort"] = pd.NaT

    active_keys = _active_url_keys(active_urls)
    active_snapshot_rows = working[working["_url_key"].isin(active_keys)].copy()
    if active_snapshot_rows.empty:
        keep_indexes: set[int] = set()
    else:
        active_snapshot_rows = active_snapshot_rows.sort_values(
            by=["_snapshot_ts_sort", "_row_order"],
            na_position="first",
        )
        keep_indexes = set(
            active_snapshot_rows.drop_duplicates(subset=["_url_key"], keep="last").index
        )

    current = working.loc[sorted(keep_indexes), original_columns].copy()
    archive = working.loc[~working.index.isin(keep_indexes), original_columns].copy()

    archive_files = _append_archive_rows(archive, archive_dir)
    write_dataframe_csv_atomic(current, snapshot_path, index=False)

    return SnapshotRetentionResult(
        current_rows=len(current),
        archived_rows=len(archive),
        archive_files=archive_files,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compact active snapshots to one latest row per active listing.",
    )
    parser.add_argument(
        "--snapshot-path",
        type=Path,
        default=DEFAULT_SNAPSHOT_PATH,
        help="Live active snapshot CSV path.",
    )
    parser.add_argument(
        "--active-path",
        type=Path,
        default=dataset_path("active_vehicle_details.csv"),
        help="Active listing CSV used to decide which URLs remain live.",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=DEFAULT_ARCHIVE_DIR,
        help="Directory for archived hourly snapshot history.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = compact_active_snapshots(
        snapshot_path=args.snapshot_path,
        active_urls=_load_active_urls(args.active_path),
        archive_dir=args.archive_dir,
    )
    archive_targets = ", ".join(str(path) for path in result.archive_files) or "none"
    print(
        "Active snapshot retention complete: "
        f"{result.current_rows} current row(s), "
        f"{result.archived_rows} archived row(s), "
        f"archive files: {archive_targets}"
    )


if __name__ == "__main__":
    main()
