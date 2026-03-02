from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import dataset_path
else:  # pragma: no cover
    from shared.data_loader import dataset_path


TRACKED_DATASETS = [
    "all_vehicle_links.csv",
    "active_vehicle_links.csv",
    "raw_vehicle_data.csv",
    "normalised_data.csv",
    "excluded_listings.csv",
    "vehicle_static_details.csv",
    "matched_canonical_details.csv",
    "unmatched_canonical_details.csv",
    "active_vehicle_details.csv",
]


@dataclass
class StageSpec:
    name: str
    command: list[str]
    expected_changes: set[str]


@dataclass
class DatasetState:
    rows: int
    mtime: Optional[float]


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return 0
    return len(df)


def _format_mtime(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return datetime.fromtimestamp(value).strftime("%H:%M:%S")


def _snapshot_state() -> dict[str, DatasetState]:
    state: dict[str, DatasetState] = {}
    for name in TRACKED_DATASETS:
        path = dataset_path(name)
        mtime = path.stat().st_mtime if path.exists() else None
        state[name] = DatasetState(rows=_read_row_count(path), mtime=mtime)
    return state


def _print_counts(title: str, state: dict[str, DatasetState]) -> None:
    print(f"\n[{_timestamp()}] {title}")
    for name in TRACKED_DATASETS:
        entry = state.get(name, DatasetState(rows=0, mtime=None))
        print(f"  {name:<32} {entry.rows:>8}   mtime={_format_mtime(entry.mtime)}")


def _print_deltas(
    before: dict[str, DatasetState],
    after: dict[str, DatasetState],
    *,
    stage_name: str,
    expected_changes: set[str] | None = None,
) -> None:
    print(f"[{_timestamp()}] Dataset deltas after {stage_name}")
    changed = False
    unexpected_changes: list[str] = []
    for name in TRACKED_DATASETS:
        prev_entry = before.get(name, DatasetState(rows=0, mtime=None))
        curr_entry = after.get(name, DatasetState(rows=0, mtime=None))
        previous = prev_entry.rows
        current = curr_entry.rows
        delta = current - previous
        marker = "+" if delta > 0 else ""
        mtime_changed = prev_entry.mtime != curr_entry.mtime
        changed_now = delta != 0 or mtime_changed
        expected = expected_changes is None or name in expected_changes
        status = ""
        if changed_now and not expected:
            status = "  [UNEXPECTED]"
            unexpected_changes.append(name)
        elif changed_now and expected:
            status = "  [expected]"
        print(
            f"  {name:<32} {previous:>8} -> {current:>8}  ({marker}{delta})"
            f"  mtime { _format_mtime(prev_entry.mtime) } -> { _format_mtime(curr_entry.mtime) }{status}"
        )
        if changed_now:
            changed = True
    if not changed:
        print("  No tracked dataset changes after this stage.")
    if unexpected_changes:
        joined = ", ".join(unexpected_changes)
        print(f"[{_timestamp()}] WARNING: unexpected dataset changes after {stage_name}: {joined}")


def _run_stage(stage: StageSpec) -> int:
    print(f"\n{'=' * 88}")
    print(f"[{_timestamp()}] Stage: {stage.name}")
    print(f"Command: {' '.join(stage.command)}")
    print(f"{'=' * 88}")
    started = time.perf_counter()
    completed = subprocess.run(stage.command, text=True, capture_output=True)
    duration = time.perf_counter() - started
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if stdout:
        print(stdout)
    if stderr:
        print("\n[stderr]")
        print(stderr)
    print(
        f"[{_timestamp()}] Stage result: exit={completed.returncode} "
        f"duration={duration:.1f}s"
    )
    return completed.returncode


def _build_stages(
    *,
    batch_size: int | None,
    checkpoint_every: int,
    include_match: bool,
    include_audit: bool,
    include_bids: bool,
    include_master: bool,
) -> list[StageSpec]:
    detail_command = [sys.executable, "scripts/extract_vehicle_details.py", "--raw-only"]
    if batch_size is not None and batch_size > 0:
        detail_command.extend(["--batch-size", str(batch_size)])
    if checkpoint_every >= 0:
        detail_command.extend(["--checkpoint-every", str(checkpoint_every)])

    stages = [
        StageSpec(
            "Extract links",
            [sys.executable, "scripts/extract_links.py"],
            {"all_vehicle_links.csv", "active_vehicle_links.csv"},
        ),
        StageSpec("Scrape details to raw", detail_command, {"raw_vehicle_data.csv"}),
        StageSpec(
            "Normalise raw -> normalised",
            [sys.executable, "scripts/pipeline_stages.py", "normalize"],
            {"normalised_data.csv"},
        ),
        StageSpec(
            "Apply exclusions + write static",
            [sys.executable, "scripts/pipeline_stages.py", "exclude"],
            {
                "excluded_listings.csv",
                "vehicle_static_details.csv",
                "active_vehicle_links.csv",
            },
        ),
    ]
    if include_match:
        stages.append(
            StageSpec(
                "Match canonical tags",
                [sys.executable, "scripts/pipeline_stages.py", "match"],
                {"matched_canonical_details.csv", "unmatched_canonical_details.csv"},
            )
        )
    if include_audit:
        stages.append(
            StageSpec(
                "Audit / lock schemas",
                [sys.executable, "scripts/pipeline_stages.py", "audit"],
                {"raw_vehicle_data.csv", "normalised_data.csv", "vehicle_static_details.csv"},
            )
        )
    if include_bids:
        bids_command = [sys.executable, "scripts/update_bids.py"]
        if not include_master:
            bids_command.append("--skip-master")
        stages.append(
            StageSpec("Update bids", bids_command, {"active_vehicle_details.csv", "sold_cars.csv"})
        )
    if include_master:
        stages.append(
            StageSpec(
                "Update master",
                [sys.executable, "scripts/update_master.py"],
                {
                    "active_vehicle_details.csv",
                    "active_vehicle_links.csv",
                    "vehicle_static_details.csv",
                },
            )
        )
    return stages


def _loop_forever(max_iterations: int | None) -> Iterable[int]:
    iteration = 1
    while max_iterations is None or iteration <= max_iterations:
        yield iteration
        iteration += 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Continuously run the Grays scraper pipeline and print stage outputs plus dataset deltas."
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.0,
        help="Pause between completed iterations (default: 0 = restart immediately).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Optional iteration cap for testing.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Optional detail scrape batch size per iteration.",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=50,
        help="Checkpoint frequency passed to extract_vehicle_details.py.",
    )
    parser.add_argument(
        "--skip-match",
        action="store_true",
        help="Skip canonical match stage.",
    )
    parser.add_argument(
        "--skip-audit",
        action="store_true",
        help="Skip schema audit stage.",
    )
    parser.add_argument(
        "--include-bids",
        action="store_true",
        help="Also run update_bids after the static pipeline stages.",
    )
    parser.add_argument(
        "--include-master",
        action="store_true",
        help="Also run update_master after the static pipeline stages.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop the loop if any stage exits non-zero.",
    )
    args = parser.parse_args()

    stages = _build_stages(
        batch_size=args.batch_size,
        checkpoint_every=args.checkpoint_every,
        include_match=not args.skip_match,
        include_audit=not args.skip_audit,
        include_bids=args.include_bids,
        include_master=args.include_master,
    )

    print("Grays pipeline loop runner")
    print(f"Stages: {', '.join(stage.name for stage in stages)}")
    print(f"Pause seconds: {args.pause_seconds}")
    print(
        "Iterations: "
        + ("continuous" if args.max_iterations is None else str(args.max_iterations))
    )
    print("Press Ctrl+C to stop.\n")

    try:
        for iteration in _loop_forever(args.max_iterations):
            print(f"\n{'#' * 88}")
            print(f"[{_timestamp()}] Pipeline iteration {iteration} starting")
            print(f"{'#' * 88}")
            before_counts = _snapshot_state()
            _print_counts("Counts before iteration", before_counts)

            failed = False
            for stage in stages:
                stage_before = _snapshot_state()
                exit_code = _run_stage(stage)
                stage_after = _snapshot_state()
                _print_deltas(
                    stage_before,
                    stage_after,
                    stage_name=stage.name,
                    expected_changes=stage.expected_changes,
                )
                if exit_code != 0:
                    failed = True
                    print(f"[{_timestamp()}] Stage failed: {stage.name}")
                    if args.stop_on_error:
                        raise RuntimeError(f"Stage failed: {stage.name} (exit {exit_code})")

            after_counts = _snapshot_state()
            _print_counts("Counts after iteration", after_counts)
            _print_deltas(
                before_counts,
                after_counts,
                stage_name="full iteration",
                expected_changes=None,
            )

            if failed:
                print(f"[{_timestamp()}] Iteration {iteration} completed with stage failures.")
            else:
                print(f"[{_timestamp()}] Iteration {iteration} completed successfully.")

            if args.pause_seconds > 0:
                print(f"[{_timestamp()}] Sleeping for {args.pause_seconds:.1f}s before next iteration.")
                time.sleep(args.pause_seconds)
    except KeyboardInterrupt:
        print(f"\n[{_timestamp()}] Pipeline loop stopped by user.")


if __name__ == "__main__":
    main()
