"""Validate and describe the governed inputs shipped with a VPS release."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.governance import validate_curve_table  # noqa: E402
from shared.repair_pricing_schedule import (  # noqa: E402
    PRICING_COLUMNS,
    validate_pricing_schedule,
)
from shared.repair_review import REVIEW_COLUMNS  # noqa: E402


GOVERNED_DATA_FILES = (
    Path("CSV_data/restricted/curves.csv"),
    Path("CSV_data/restricted/versions/curves_manifest.csv"),
    Path("CSV_data/reports/repair_pricing_schedule.csv"),
    Path("CSV_data/reports/repair_review_decisions.csv"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_row_count(path: Path) -> int:
    return len(pd.read_csv(path))


def _release_files(root: Path) -> list[Path]:
    config_root = root / "config"
    config_files = [
        path.relative_to(root)
        for path in config_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    files = {*GOVERNED_DATA_FILES, *config_files}
    curve_manifest = root / "CSV_data/restricted/versions/curves_manifest.csv"
    if curve_manifest.is_file():
        try:
            manifest = pd.read_csv(curve_manifest).fillna("")
            if not manifest.empty and "snapshot_path" in manifest.columns:
                files.add(Path(str(manifest.iloc[-1]["snapshot_path"]).strip()))
        except Exception:
            # The dedicated validator will provide the actionable manifest error.
            pass
    return sorted(files, key=lambda path: path.as_posix())


def _validate_curve_manifest(root: Path, curves: pd.DataFrame) -> list[str]:
    path = root / "CSV_data/restricted/versions/curves_manifest.csv"
    manifest = pd.read_csv(path).fillna("")
    required = {
        "snapshot_path",
        "row_count",
        "canonical_tag_count",
        "sha256",
    }
    missing = sorted(required - set(manifest.columns))
    if missing:
        return [f"Curve manifest is missing columns: {', '.join(missing)}"]
    if manifest.empty:
        return ["Curve manifest is empty."]

    latest = manifest.iloc[-1]
    snapshot_rel = Path(str(latest["snapshot_path"]).strip())
    snapshot = root / snapshot_rel
    errors: list[str] = []
    if not snapshot.is_file():
        errors.append(f"Latest curve snapshot is missing: {snapshot_rel.as_posix()}")
        return errors

    curves_path = root / "CSV_data/restricted/curves.csv"
    current_hash = _sha256(curves_path)
    snapshot_hash = _sha256(snapshot)
    expected_hash = str(latest["sha256"]).strip().lower()
    if current_hash != snapshot_hash:
        errors.append("Current curves.csv does not match the latest versioned snapshot.")
    if expected_hash != current_hash:
        errors.append("Latest curve manifest SHA-256 does not match curves.csv.")

    try:
        expected_rows = int(latest["row_count"])
        expected_tags = int(latest["canonical_tag_count"])
    except (TypeError, ValueError):
        errors.append("Latest curve manifest row/tag counts are not integers.")
        return errors
    if expected_rows != len(curves):
        errors.append(f"Curve manifest row_count={expected_rows} but curves.csv has {len(curves)} rows.")
    actual_tags = int(curves["canonical_tag"].astype(str).str.strip().nunique())
    if expected_tags != actual_tags:
        errors.append(
            f"Curve manifest canonical_tag_count={expected_tags} but curves.csv has {actual_tags} tags."
        )
    return errors


def validate_release(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for relative in _release_files(root):
        if not (root / relative).is_file():
            errors.append(f"Missing governed release file: {relative.as_posix()}")
    if errors:
        return errors

    curves = pd.read_csv(root / "CSV_data/restricted/curves.csv")
    errors.extend(validate_curve_table(curves))
    errors.extend(_validate_curve_manifest(root, curves))

    pricing = pd.read_csv(root / "CSV_data/reports/repair_pricing_schedule.csv").fillna("")
    missing_pricing = sorted(set(PRICING_COLUMNS) - set(pricing.columns))
    if missing_pricing:
        errors.append(f"Repair pricing schedule is missing columns: {', '.join(missing_pricing)}")
    else:
        errors.extend(validate_pricing_schedule(pricing))

    decisions = pd.read_csv(root / "CSV_data/reports/repair_review_decisions.csv").fillna("")
    missing_decisions = sorted(set(REVIEW_COLUMNS) - set(decisions.columns))
    unexpected_decisions = sorted(set(decisions.columns) - set(REVIEW_COLUMNS))
    if missing_decisions or unexpected_decisions:
        errors.append(
            "Repair review decision schema mismatch; "
            f"missing={missing_decisions or []} unexpected={unexpected_decisions or []}"
        )
    return errors


def build_manifest(root: Path, *, commit: str) -> dict[str, Any]:
    root = root.resolve()
    files: list[dict[str, Any]] = []
    for relative in _release_files(root):
        path = root / relative
        record: dict[str, Any] = {
            "path": relative.as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        if path.suffix.lower() == ".csv":
            record["rows"] = _csv_row_count(path)
        files.append(record)
    return {
        "format_version": 1,
        "commit": commit,
        "released_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--write", type=Path)
    args = parser.parse_args()

    errors = validate_release(args.root)
    if errors:
        for error in errors:
            print(f"RELEASE_INVALID: {error}", file=sys.stderr)
        return 1

    manifest = build_manifest(args.root, commit=args.commit)
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        "RELEASE_VALID "
        f"commit={args.commit} files={len(manifest['files'])} "
        f"curves={next(item['rows'] for item in manifest['files'] if item['path'].endswith('/curves.csv'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
