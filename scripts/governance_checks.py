from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.curve_versioning import snapshot_curve_version
    from shared.data_loader import dataset_path
    from shared.governance import (
        build_curve_coverage_report,
        classify_dataset_deltas,
        render_curve_coverage_markdown,
        summarize_curve_coverage,
        validate_curves_dataset,
        validate_dataset_contracts,
    )
else:  # pragma: no cover
    from shared.curve_versioning import snapshot_curve_version
    from shared.data_loader import dataset_path
    from shared.governance import (
        build_curve_coverage_report,
        classify_dataset_deltas,
        render_curve_coverage_markdown,
        summarize_curve_coverage,
        validate_curves_dataset,
        validate_dataset_contracts,
    )


DEFAULT_REPORT_DIR = Path("output/governance")
CURVES_PRIMARY_FILE = "CSV_data/restricted/curves.csv"
CURVES_MANIFEST_FILE = "CSV_data/restricted/versions/curves_manifest.csv"
CHANGELOG_FILE = "CHANGELOG.md"


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_git(args: list[str]) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]


def _git_changed_paths(base_ref: str | None, head_ref: str) -> list[str]:
    if base_ref and set(base_ref) != {"0"}:
        return _run_git(["diff", "--name-only", f"{base_ref}...{head_ref}"])
    try:
        return _run_git(["diff", "--name-only", "HEAD~1...HEAD"])
    except RuntimeError:
        return _run_git(["diff", "--name-only"])


def _effective_allowed_dataset_changes(
    changed_paths: list[str],
    explicit_allowlist: list[str],
) -> list[str]:
    allowlist = list(explicit_allowlist)
    if CURVES_PRIMARY_FILE not in changed_paths:
        return allowlist
    has_manifest = CURVES_MANIFEST_FILE in changed_paths
    has_changelog = CHANGELOG_FILE in changed_paths
    has_snapshot = any(
        path.startswith("CSV_data/restricted/versions/curves_") and path.endswith(".csv")
        for path in changed_paths
    )
    if has_manifest and has_changelog and has_snapshot:
        allowlist.append(CURVES_PRIMARY_FILE)
    return allowlist


def _build_coverage_outputs(report_dir: Path) -> tuple[pd.DataFrame, dict[str, int], Path, Path]:
    static_df = _load_csv(dataset_path("vehicle_static_details.csv"))
    group_map_df = _load_csv(dataset_path("restricted_group_map.csv"))
    curves_df = _load_csv(dataset_path("curves.csv"))
    coverage_df = build_curve_coverage_report(static_df, group_map_df, curves_df)
    summary = summarize_curve_coverage(coverage_df)
    csv_path = report_dir / "curve_coverage.csv"
    md_path = report_dir / "curve_coverage.md"
    report_dir.mkdir(parents=True, exist_ok=True)
    coverage_df.to_csv(csv_path, index=False)
    _write_text(md_path, render_curve_coverage_markdown(coverage_df))
    return coverage_df, summary, csv_path, md_path


def _append_job_summary(path: Path) -> None:
    summary_file = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_file:
        return
    with Path(summary_file).open("a", encoding="utf-8") as handle:
        handle.write(path.read_text(encoding="utf-8"))
        handle.write("\n")


def command_check(args: argparse.Namespace) -> int:
    errors: list[str] = []

    if not args.skip_schema:
        errors.extend(validate_dataset_contracts())

    if not args.skip_curves:
        errors.extend(validate_curves_dataset())

    coverage_summary: dict[str, int] | None = None
    report_paths: tuple[Path, Path] | None = None
    if not args.skip_coverage:
        _, coverage_summary, csv_path, md_path = _build_coverage_outputs(args.report_dir)
        report_paths = (csv_path, md_path)
        print(
            "[governance] curve coverage "
            f"observed_tags={coverage_summary['observed_tags']} "
            f"covered_tags={coverage_summary['covered_tags']} "
            f"missing_tags={coverage_summary['missing_tags']}"
        )
        if args.publish_summary:
            _append_job_summary(md_path)

    if not args.skip_dataset_delta:
        changed_paths = _git_changed_paths(args.base_ref, args.head_ref)
        allowed_patterns = _effective_allowed_dataset_changes(
            changed_paths,
            list(args.allow_dataset_change or []),
        )
        report = classify_dataset_deltas(changed_paths, allowed_patterns=allowed_patterns)
        print(
            "[governance] dataset delta "
            f"tracked={len(report['tracked'])} allowed={len(report['allowed'])} "
            f"unexpected={len(report['unexpected'])}"
        )
        if report["unexpected"]:
            errors.append(
                "Unexpected tracked dataset changes detected: "
                + ", ".join(report["unexpected"])
            )

    if report_paths:
        print(f"[governance] coverage report -> {report_paths[0]}")
        print(f"[governance] coverage summary -> {report_paths[1]}")

    if errors:
        for error in errors:
            print(f"[governance] ERROR: {error}", file=sys.stderr)
        return 1

    print("[governance] all checks passed")
    return 0


def command_coverage_report(args: argparse.Namespace) -> int:
    _, summary, csv_path, md_path = _build_coverage_outputs(args.report_dir)
    print(f"[governance] coverage report -> {csv_path}")
    print(f"[governance] markdown report -> {md_path}")
    print(
        "[governance] summary "
        f"observed_tags={summary['observed_tags']} "
        f"covered_tags={summary['covered_tags']} "
        f"missing_tags={summary['missing_tags']}"
    )
    if args.publish_summary:
        _append_job_summary(md_path)
    return 0


def command_snapshot_curves(args: argparse.Namespace) -> int:
    curves_path = dataset_path("curves.csv")
    snapshot_path = snapshot_curve_version(
        curves_path,
        source=args.source,
        change_summary=args.note or "",
    )
    if snapshot_path is None:
        print(f"[governance] curves snapshot skipped: {curves_path} not found")
        return 1
    print(f"[governance] curves snapshot -> {snapshot_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Governance checks for datasets, curves, and CI deltas.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Run governance checks.")
    check_parser.add_argument("--skip-schema", action="store_true", help="Skip dataset schema checks.")
    check_parser.add_argument("--skip-curves", action="store_true", help="Skip curve integrity checks.")
    check_parser.add_argument("--skip-coverage", action="store_true", help="Skip coverage report generation.")
    check_parser.add_argument("--skip-dataset-delta", action="store_true", help="Skip git dataset delta checks.")
    check_parser.add_argument("--base-ref", default=os.getenv("GOVERNANCE_BASE_SHA", "").strip() or None)
    check_parser.add_argument("--head-ref", default="HEAD")
    check_parser.add_argument(
        "--allow-dataset-change",
        action="append",
        default=[
            value.strip()
            for value in os.getenv("AUTOSNIPER_EXPECTED_DATASET_CHANGES", "").split(",")
            if value.strip()
        ],
        help="Allowlisted tracked dataset path or glob pattern. Repeat as needed.",
    )
    check_parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory for generated governance reports.",
    )
    check_parser.add_argument(
        "--publish-summary",
        action="store_true",
        help="Append markdown coverage output to GITHUB_STEP_SUMMARY.",
    )
    check_parser.set_defaults(func=command_check)

    coverage_parser = subparsers.add_parser("coverage-report", help="Generate only the curve coverage report.")
    coverage_parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory for generated governance reports.",
    )
    coverage_parser.add_argument(
        "--publish-summary",
        action="store_true",
        help="Append markdown coverage output to GITHUB_STEP_SUMMARY.",
    )
    coverage_parser.set_defaults(func=command_coverage_report)

    snapshot_parser = subparsers.add_parser("snapshot-curves", help="Version the current curves.csv file.")
    snapshot_parser.add_argument("--note", default="", help="Optional changelog note for the manifest entry.")
    snapshot_parser.add_argument("--source", default="manual", help="Snapshot source label.")
    snapshot_parser.set_defaults(func=command_snapshot_curves)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
