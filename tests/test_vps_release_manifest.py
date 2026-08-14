from pathlib import Path
import shutil

import pandas as pd

from scripts.vps_release_manifest import build_manifest, validate_release


ROOT = Path(__file__).resolve().parents[1]


def _copy_release_fixture(target: Path) -> Path:
    for relative in (
        "config",
        "CSV_data/restricted/curves.csv",
        "CSV_data/restricted/versions/curves_manifest.csv",
        "CSV_data/reports/repair_pricing_schedule.csv",
        "CSV_data/reports/repair_review_decisions.csv",
    ):
        source = ROOT / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    manifest = pd.read_csv(target / "CSV_data/restricted/versions/curves_manifest.csv")
    snapshot_relative = Path(str(manifest.iloc[-1]["snapshot_path"]))
    snapshot_source = ROOT / snapshot_relative
    snapshot_destination = target / snapshot_relative
    snapshot_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snapshot_source, snapshot_destination)
    return target


def test_current_governed_release_is_valid_and_manifested() -> None:
    assert validate_release(ROOT) == []

    manifest = build_manifest(ROOT, commit="a" * 40)

    assert manifest["commit"] == "a" * 40
    records = {item["path"]: item for item in manifest["files"]}
    assert records["CSV_data/restricted/curves.csv"]["rows"] > 0
    assert records["CSV_data/reports/repair_pricing_schedule.csv"]["rows"] > 0
    assert len(records["CSV_data/restricted/curves.csv"]["sha256"]) == 64


def test_release_rejects_duplicate_repair_pricing_keys(tmp_path: Path) -> None:
    release_root = _copy_release_fixture(tmp_path)
    schedule_path = release_root / "CSV_data/reports/repair_pricing_schedule.csv"
    schedule = pd.read_csv(schedule_path)
    schedule = pd.concat([schedule, schedule.iloc[[0]]], ignore_index=True)
    schedule.to_csv(schedule_path, index=False)

    errors = validate_release(release_root)

    assert any("Duplicate canonical defect/vehicle class rows" in error for error in errors)


def test_release_rejects_duplicate_repair_decision_keys(tmp_path: Path) -> None:
    release_root = _copy_release_fixture(tmp_path)
    decisions_path = release_root / "CSV_data/reports/repair_review_decisions.csv"
    decisions = pd.read_csv(decisions_path)
    decisions = pd.concat([decisions, decisions.iloc[[0]]], ignore_index=True)
    decisions.to_csv(decisions_path, index=False)

    errors = validate_release(release_root)

    assert any("duplicate repair_key rows" in error for error in errors)


def test_release_rejects_curve_snapshot_drift(tmp_path: Path) -> None:
    release_root = _copy_release_fixture(tmp_path)
    curves_path = release_root / "CSV_data/restricted/curves.csv"
    curves = pd.read_csv(curves_path)
    curves.loc[0, "price_mid"] = float(curves.loc[0, "price_mid"]) + 1
    curves.to_csv(curves_path, index=False)

    errors = validate_release(release_root)

    assert any("does not match the latest versioned snapshot" in error for error in errors)


def test_release_accepts_manifest_hash_across_csv_line_endings(tmp_path: Path) -> None:
    release_root = _copy_release_fixture(tmp_path)
    manifest = pd.read_csv(release_root / "CSV_data/restricted/versions/curves_manifest.csv")
    paths = [
        release_root / "CSV_data/restricted/curves.csv",
        release_root / Path(str(manifest.iloc[-1]["snapshot_path"])),
    ]
    for path in paths:
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))

    errors = validate_release(release_root)

    assert "Latest curve manifest SHA-256 does not match curves.csv." not in errors
