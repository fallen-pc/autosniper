from __future__ import annotations

import argparse
import csv
import io
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_RUNTIME_PATHS = (
    "CSV_data/scrapers",
    "CSV_data/restricted",
    "CSV_data/ai",
    "CSV_data/model_audit",
    "CSV_data/reports",
    "status",
    "output/health",
    "logs/scheduled",
)
AUTOTRADER_SESSION_PATH = "autotrader_isolated/output"
REQUIRED_CSV_CHECKS = (
    ("CSV_data/scrapers/sold_cars.csv", 1),
    ("CSV_data/restricted/sold_cars_restricted.csv", 1),
    ("CSV_data/ai/ai_listing_valuations.csv", 0),
)


def _env_flag_enabled(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _archive_files(root: Path) -> Iterable[Path]:
    if root.is_symlink():
        return
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_file():
            yield path


def create_runtime_backup(
    *,
    repo_root: Path,
    backup_dir: Path,
    include_autotrader_session: bool = False,
    created_at: datetime | None = None,
) -> Path:
    repo_root = repo_root.resolve()
    backup_dir = backup_dir.expanduser().resolve()
    if backup_dir.is_relative_to(repo_root):
        raise ValueError("Backup directory must be outside the repository runtime tree.")

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = created_at or datetime.now(timezone.utc)
    final_path = backup_dir / f"autosniper-runtime-{timestamp.strftime('%Y%m%d-%H%M%S')}.zip"
    if final_path.exists():
        raise FileExistsError(f"Runtime backup already exists: {final_path}")

    relative_paths = list(DEFAULT_RUNTIME_PATHS)
    if include_autotrader_session:
        relative_paths.append(AUTOTRADER_SESSION_PATH)

    included_paths: list[str] = []
    missing_paths: list[str] = []
    for relative_path in relative_paths:
        if (repo_root / relative_path).exists():
            included_paths.append(relative_path)
        else:
            missing_paths.append(relative_path)
    if not included_paths:
        raise FileNotFoundError("No runtime paths were found to back up.")

    manifest_lines = [
        "AutoSniper runtime backup",
        f"created_at={timestamp.astimezone(timezone.utc).isoformat()}",
        f"repo_root={repo_root}",
        f"zip_path={final_path}",
        f"include_autotrader_session={include_autotrader_session}",
        "",
        "included_paths:",
        *(f"- {path}" for path in included_paths),
        "",
        "missing_paths:",
        *(f"- {path}" for path in missing_paths),
    ]

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{final_path.stem}-",
        suffix=".zip.tmp",
        dir=backup_dir,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        os.chmod(temporary_path, 0o600)
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            archive.writestr("backup_manifest.txt", "\n".join(manifest_lines) + "\n")
            for relative_path in included_paths:
                source_path = repo_root / relative_path
                for file_path in _archive_files(source_path):
                    archive.write(file_path, arcname=file_path.relative_to(repo_root).as_posix())
        temporary_path.replace(final_path)
        os.chmod(final_path, 0o600)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return final_path


def verify_runtime_backup(backup_zip: Path) -> dict[str, int]:
    backup_zip = backup_zip.expanduser().resolve()
    if not backup_zip.is_file():
        raise FileNotFoundError(f"Runtime backup does not exist: {backup_zip}")

    row_counts: dict[str, int] = {}
    with zipfile.ZipFile(backup_zip, mode="r") as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"Runtime backup CRC check failed: {bad_member}")
        members = set(archive.namelist())
        if "backup_manifest.txt" not in members:
            raise ValueError("Runtime backup is missing backup_manifest.txt")
        for member, minimum_rows in REQUIRED_CSV_CHECKS:
            if member not in members:
                raise ValueError(f"Runtime backup is missing required file: {member}")
            with archive.open(member, mode="r") as raw_file:
                with io.TextIOWrapper(raw_file, encoding="utf-8-sig", newline="") as text_file:
                    row_count = max(0, sum(1 for _ in csv.reader(text_file)) - 1)
            if row_count < minimum_rows:
                raise ValueError(f"Runtime backup row count is too low for {member}: {row_count}")
            row_counts[member] = row_count

        queue_member = "CSV_data/reports/repair_review_live_queue.csv"
        if queue_member in members:
            with archive.open(queue_member, mode="r") as raw_file:
                with io.TextIOWrapper(raw_file, encoding="utf-8-sig", newline="") as text_file:
                    row_counts[queue_member] = max(0, sum(1 for _ in csv.reader(text_file)) - 1)

    return row_counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create and verify an AutoSniper runtime backup.")
    parser.add_argument("--repo-root", type=Path, default=ROOT_DIR)
    parser.add_argument("--backup-dir", type=Path, default=os.getenv("AUTOSNIPER_BACKUP_DIR"))
    parser.add_argument("--include-autotrader-session", action="store_true")
    parser.add_argument("--verify-zip", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.verify_zip:
        backup_path = args.verify_zip
    else:
        if args.backup_dir is None:
            raise ValueError("Backup directory is required. Set AUTOSNIPER_BACKUP_DIR or pass --backup-dir.")
        backup_path = create_runtime_backup(
            repo_root=args.repo_root,
            backup_dir=args.backup_dir,
            include_autotrader_session=(
                args.include_autotrader_session
                or _env_flag_enabled("AUTOSNIPER_BACKUP_INCLUDE_AUTOTRADER_SESSION")
            ),
        )
        print(f"Backup created: {backup_path}")
        print(f"Size MB: {backup_path.stat().st_size / (1024 * 1024):.2f}")

    row_counts = verify_runtime_backup(backup_path)
    for member, row_count in row_counts.items():
        print(f"Verified {member}: {row_count} rows")
    print(f"Backup verification passed: {backup_path}")


if __name__ == "__main__":
    main()
