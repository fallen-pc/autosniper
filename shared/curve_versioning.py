"""Version snapshots for restricted curve datasets."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


VERSION_DIRNAME = "versions"
MANIFEST_FILENAME = "curves_manifest.csv"
MANIFEST_COLUMNS = [
    "version_id",
    "created_at",
    "source",
    "curve_path",
    "snapshot_path",
    "row_count",
    "canonical_tag_count",
    "sha256",
    "change_summary",
]


def _manifest_path_value(path: Path) -> str:
    """Store repository-owned paths portably while leaving external test paths intact."""
    repo_root = Path(__file__).resolve().parent.parent
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(manifest_path: Path) -> pd.DataFrame:
    if not manifest_path.exists():
        return pd.DataFrame(columns=MANIFEST_COLUMNS)
    try:
        manifest_df = pd.read_csv(manifest_path)
    except (ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=MANIFEST_COLUMNS)
    for column in MANIFEST_COLUMNS:
        if column not in manifest_df.columns:
            manifest_df[column] = ""
    return manifest_df.reindex(columns=MANIFEST_COLUMNS)


def snapshot_curve_version(
    curves_path: Path,
    *,
    source: str = "save_curves",
    change_summary: str = "",
) -> Path | None:
    if not curves_path.exists():
        return None

    version_dir = curves_path.parent / VERSION_DIRNAME
    version_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = version_dir / MANIFEST_FILENAME
    manifest_df = _load_manifest(manifest_path)
    file_hash = _file_sha256(curves_path)

    if not manifest_df.empty and "sha256" in manifest_df.columns:
        matching = manifest_df[manifest_df["sha256"].astype(str) == file_hash]
        if not matching.empty:
            snapshot_value = str(matching.iloc[-1]["snapshot_path"]).strip()
            return Path(snapshot_value) if snapshot_value else None

    curves_df = pd.read_csv(curves_path)
    version_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = version_dir / f"{curves_path.stem}_{version_id}.csv"
    suffix = 1
    while snapshot_path.exists():
        snapshot_path = version_dir / f"{curves_path.stem}_{version_id}_{suffix:02d}.csv"
        suffix += 1

    shutil.copy2(curves_path, snapshot_path)

    manifest_row = pd.DataFrame(
        [
            {
                "version_id": snapshot_path.stem.replace(f"{curves_path.stem}_", "", 1),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": source,
                "curve_path": _manifest_path_value(curves_path),
                "snapshot_path": _manifest_path_value(snapshot_path),
                "row_count": int(len(curves_df)),
                "canonical_tag_count": int(curves_df.get("canonical_tag", pd.Series(dtype=object)).nunique()),
                "sha256": file_hash,
                "change_summary": change_summary.strip(),
            }
        ],
        columns=MANIFEST_COLUMNS,
    )
    manifest_out = pd.concat([manifest_df, manifest_row], ignore_index=True)
    manifest_out.to_csv(manifest_path, index=False)
    return snapshot_path


def latest_prior_curve_snapshot(curves_path: Path) -> Path | None:
    """Return the most recent snapshot with different content from the current curves file."""
    if not curves_path.exists():
        return None

    manifest_path = curves_path.parent / VERSION_DIRNAME / MANIFEST_FILENAME
    manifest_df = _load_manifest(manifest_path)
    if manifest_df.empty:
        return None

    current_hash = _file_sha256(curves_path)
    candidates = manifest_df[manifest_df["sha256"].astype(str) != current_hash].copy()
    if candidates.empty:
        return None

    for snapshot_value in reversed(candidates["snapshot_path"].astype(str).tolist()):
        snapshot_path = Path(snapshot_value)
        if snapshot_path.exists():
            return snapshot_path
    return None
