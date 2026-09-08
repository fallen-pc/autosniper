"""Refresh the local-only repair ledgers from VPS-owned runtime evidence.

The VPS remains the scraper/data authority. This script pulls only the runtime
inputs used by Repair Review and Repair Pricing, preserves the locally authored
decisions, pricing schedule, and quote-request ledger, then rebuilds derived
artifacts only when their inputs are newer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_VPS_HOST = "134.199.144.141"
DEFAULT_VPS_USER = "root"
DEFAULT_REMOTE_ROOT = "/opt/autosniper"
DEFAULT_KEY_PATH = Path.home() / ".ssh" / "autosniper_digitalocean"
STATE_PATH = ROOT_DIR / "status" / "repair_ledger_refresh.json"

# These are runtime-owned inputs. Do not add locally authored files such as
# repair_review_decisions.csv, repair_pricing_schedule.csv, or
# repair_quote_requests.csv to this list.
RUNTIME_SOURCE_PATHS = (
    Path("CSV_data/scrapers/active_vehicle_details.csv"),
    Path("CSV_data/scrapers/vehicle_static_details.csv"),
    Path("CSV_data/scrapers/sold_cars.csv"),
    Path("CSV_data/scrapers/referred_cars.csv"),
    Path("CSV_data/scrapers/sold_price_pending.csv"),
    Path("CSV_data/reports/repair_review_live_queue.csv"),
)

REPAIR_AUDIT_INPUTS = (
    *RUNTIME_SOURCE_PATHS[:5],
    Path("CSV_data/restricted/active_vehicle_details_restricted.csv"),
    Path("CSV_data/restricted/sold_cars_restricted.csv"),
    Path("CSV_data/archives/sold_cars_rescraped.csv"),
    Path("CSV_data/archives/sold_cars_historical.csv"),
)
REPAIR_AUDIT_OUTPUTS = (
    Path("CSV_data/reports/grays_condition_repair_lines.csv"),
    Path("CSV_data/reports/grays_condition_repair_fragments.csv"),
    Path("CSV_data/reports/grays_condition_repair_summary.json"),
)
PRICING_MATRIX_INPUTS = (
    Path("CSV_data/scrapers/sold_cars.csv"),
    Path("CSV_data/reports/repair_review_decisions.csv"),
    Path("CSV_data/reports/repair_pricing_schedule.csv"),
)
PRICING_MATRIX_OUTPUTS = (Path("CSV_data/model_audit/repair_pricing_matrix.csv"),)

REQUIRED_COLUMNS = {
    Path("CSV_data/scrapers/active_vehicle_details.csv"): {"url", "general_condition"},
    Path("CSV_data/scrapers/vehicle_static_details.csv"): {"url", "general_condition"},
    Path("CSV_data/scrapers/sold_cars.csv"): {"url", "general_condition"},
    Path("CSV_data/scrapers/referred_cars.csv"): {"url", "general_condition"},
    Path("CSV_data/scrapers/sold_price_pending.csv"): {"url"},
    Path("CSV_data/reports/repair_review_live_queue.csv"): {
        "repair_key",
        "source_file",
        "example_urls",
    },
}


def _rooted(paths: Iterable[Path]) -> list[Path]:
    return [ROOT_DIR / path for path in paths]


def outputs_are_stale(inputs: Iterable[Path], outputs: Iterable[Path]) -> bool:
    """Return true when an output is missing or older than any existing input."""
    input_paths = [path for path in inputs if path.exists()]
    output_paths = list(outputs)
    if not input_paths or not output_paths or any(not path.exists() for path in output_paths):
        return True
    newest_input = max(path.stat().st_mtime_ns for path in input_paths)
    oldest_output = min(path.stat().st_mtime_ns for path in output_paths)
    return oldest_output < newest_input


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_download(relative_path: Path, downloaded_path: Path) -> None:
    if not downloaded_path.is_file() or downloaded_path.stat().st_size == 0:
        raise RuntimeError(f"Downloaded VPS source is empty: {relative_path.as_posix()}")
    required = REQUIRED_COLUMNS.get(relative_path, set())
    if not required:
        return
    columns = set(pd.read_csv(downloaded_path, nrows=0).columns)
    missing = sorted(required - columns)
    if missing:
        raise RuntimeError(
            f"Downloaded VPS source {relative_path.as_posix()} is missing columns: {', '.join(missing)}"
        )


def sync_runtime_sources(
    *,
    host: str,
    user: str,
    key_path: Path,
    remote_root: str,
) -> list[str]:
    """Download, validate, and atomically install VPS-owned repair inputs."""
    if not key_path.is_file():
        raise FileNotFoundError(f"VPS SSH key not found: {key_path}")

    status_dir = ROOT_DIR / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="repair-ledger-sync-", dir=status_dir) as temp_name:
        temp_dir = Path(temp_name)
        downloads: list[tuple[Path, Path]] = []
        for index, relative_path in enumerate(RUNTIME_SOURCE_PATHS):
            downloaded_path = temp_dir / f"{index:02d}-{relative_path.name}"
            remote_path = f"{remote_root.rstrip('/')}/{relative_path.as_posix()}"
            subprocess.run(
                [
                    "scp",
                    "-q",
                    "-p",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=15",
                    "-i",
                    str(key_path),
                    f"{user}@{host}:{remote_path}",
                    str(downloaded_path),
                ],
                check=True,
            )
            _validate_download(relative_path, downloaded_path)
            downloads.append((relative_path, downloaded_path))

        for relative_path, downloaded_path in downloads:
            destination = ROOT_DIR / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and _sha256(destination) == _sha256(downloaded_path):
                continue
            os.replace(downloaded_path, destination)
            changed.append(relative_path.as_posix())
    return changed


def _run_builder(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def refresh_derived_ledgers(*, force: bool = False) -> tuple[bool, bool]:
    audit_stale = force or outputs_are_stale(
        _rooted(REPAIR_AUDIT_INPUTS),
        _rooted(REPAIR_AUDIT_OUTPUTS),
    )
    matrix_stale = force or outputs_are_stale(
        _rooted(PRICING_MATRIX_INPUTS),
        _rooted(PRICING_MATRIX_OUTPUTS),
    )

    if audit_stale:
        _run_builder([sys.executable, str(ROOT_DIR / "scripts" / "extract_grays_condition_repairs.py")])
    else:
        print("Repair Review audit is current; rebuild skipped.")

    if matrix_stale:
        _run_builder(
            [
                sys.executable,
                "-m",
                "scripts.build_repair_pricing_matrix",
                "--limit",
                "0",
            ]
        )
    else:
        print("Repair Pricing matrix is current; rebuild skipped.")
    return audit_stale, matrix_stale


def _write_state(*, changed_sources: list[str], audit_rebuilt: bool, matrix_rebuilt: bool) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "success",
        "completed_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "changed_sources": changed_sources,
        "repair_review_rebuilt": audit_rebuilt,
        "repair_pricing_rebuilt": matrix_rebuilt,
    }
    temporary = STATE_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, STATE_PATH)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh local Repair Review and Repair Pricing ledgers.")
    parser.add_argument("--vps-host", default=os.getenv("AUTOSNIPER_VPS_HOST", DEFAULT_VPS_HOST))
    parser.add_argument("--vps-user", default=os.getenv("AUTOSNIPER_VPS_USER", DEFAULT_VPS_USER))
    parser.add_argument("--key-path", type=Path, default=DEFAULT_KEY_PATH)
    parser.add_argument("--remote-root", default=os.getenv("AUTOSNIPER_VPS_ROOT", DEFAULT_REMOTE_ROOT))
    parser.add_argument("--skip-vps-sync", action="store_true")
    parser.add_argument("--force", action="store_true", help="Rebuild derived ledgers even when outputs are current.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    changed_sources: list[str] = []
    if args.skip_vps_sync:
        print("VPS source sync skipped by request.")
    else:
        changed_sources = sync_runtime_sources(
            host=args.vps_host,
            user=args.vps_user,
            key_path=args.key_path,
            remote_root=args.remote_root,
        )
        print(f"VPS source sync complete: {len(changed_sources)} changed file(s).")

    audit_rebuilt, matrix_rebuilt = refresh_derived_ledgers(force=args.force)
    _write_state(
        changed_sources=changed_sources,
        audit_rebuilt=audit_rebuilt,
        matrix_rebuilt=matrix_rebuilt,
    )
    print(f"Repair ledger refresh complete: {STATE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
