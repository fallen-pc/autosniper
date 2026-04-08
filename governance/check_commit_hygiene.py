from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from shared.project_memory_guard import MEMORY_WRITE_APPROVAL_ENV, validate_protected_memory_changes

SOURCE_PREFIXES = (
    ".github/",
    ".streamlit/",
    "config/",
    "docs/",
    "pages/",
    "scripts/",
    "shared/",
    "tests/",
    "governance/",
)

SOURCE_FILES = {
    ".gitattributes",
    ".gitignore",
    "DASHBOARD.py",
    "README.md",
    "requirements.txt",
    "status_app.py",
}

SOURCE_EXTENSIONS = {
    ".bat",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

ARTIFACT_PREFIXES = (
    "CSV_data/",
    "artifacts/",
    "autotrader_isolated/output/",
    "catboost_info/",
    "curves/images/",
    "logs/",
    "output/",
)

ARTIFACT_EXTENSIONS = {
    ".cbm",
    ".csv",
    ".gif",
    ".jpeg",
    ".jpg",
    ".npy",
    ".npz",
    ".parquet",
    ".pkl",
    ".png",
    ".tsv",
    ".zip",
}

CURVES_PRIMARY_FILE = "CSV_data/restricted/curves.csv"
CURVES_MANIFEST_FILE = "CSV_data/restricted/versions/curves_manifest.csv"
CHANGELOG_FILE = "CHANGELOG.md"
BAD_SOURCE_TOKENS = {"backup", "copy", "final", "old", "temp", "tmp"}
NAMING_GUARD_PREFIXES = ("scripts/", "shared/", "docs/", "governance/")


def _run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def _repo_root() -> Path:
    root = _run_git(["rev-parse", "--show-toplevel"]).strip()
    return Path(root)


def _normalized_nonempty_lines(output: str) -> list[str]:
    return [line.replace("\\", "/").strip() for line in output.splitlines() if line.strip()]


def _staged_paths() -> list[str]:
    output = _run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return _normalized_nonempty_lines(output)


def _added_paths() -> list[str]:
    output = _run_git(["diff", "--cached", "--name-status", "--diff-filter=A"])
    paths: list[str] = []
    for line in _normalized_nonempty_lines(output):
        _, _, rel_path = line.partition("\t")
        if rel_path:
            paths.append(rel_path)
    return paths


def _classify(path: str) -> str:
    lowered = path.lower()
    suffix = Path(lowered).suffix
    if path in SOURCE_FILES or any(lowered.startswith(prefix) for prefix in SOURCE_PREFIXES):
        return "source"
    if any(lowered.startswith(prefix) for prefix in ARTIFACT_PREFIXES):
        return "artifact"
    if suffix in SOURCE_EXTENSIONS:
        return "source"
    if suffix in ARTIFACT_EXTENSIONS:
        return "artifact"
    return "source"


def _format_list(values: list[str], max_items: int = 12) -> str:
    clipped = values[:max_items]
    extra = len(values) - len(clipped)
    lines = [f"  - {value}" for value in clipped]
    if extra > 0:
        lines.append(f"  - ... and {extra} more")
    return "\n".join(lines)


def _find_bad_source_names(paths: list[str]) -> list[str]:
    flagged: list[str] = []
    for rel_path in paths:
        lowered = rel_path.lower()
        if not any(lowered.startswith(prefix) for prefix in NAMING_GUARD_PREFIXES):
            continue
        if "/archive/" in lowered or "/archives/" in lowered:
            continue
        stem_tokens = [token for token in re.split(r"[^a-z0-9]+", Path(lowered).stem) if token]
        if any(token in BAD_SOURCE_TOKENS for token in stem_tokens):
            flagged.append(rel_path)
    return flagged


def main() -> int:
    parser = argparse.ArgumentParser(description="Guardrail checks for commit slicing/artifact hygiene.")
    parser.add_argument("--staged", action="store_true", help="Validate staged files.")
    args = parser.parse_args()

    if not args.staged:
        print("Nothing to do. Use --staged.")
        return 0

    try:
        repo_root = _repo_root()
        staged = _staged_paths()
        added = _added_paths()
    except RuntimeError as exc:
        print(f"[commit-hygiene] {exc}", file=sys.stderr)
        return 2

    if not staged:
        return 0

    allow_mixed = os.getenv("AUTOSNIPER_ALLOW_MIXED_COMMIT", "").strip() == "1"
    max_files = int(os.getenv("AUTOSNIPER_MAX_COMMIT_FILES", "80"))
    max_file_bytes = int(os.getenv("AUTOSNIPER_MAX_FILE_BYTES", "1000000"))

    source_files: list[str] = []
    artifact_files: list[str] = []
    oversize_files: list[tuple[str, int]] = []
    bad_source_names = _find_bad_source_names(added)

    for rel_path in staged:
        classification = _classify(rel_path)
        if classification == "artifact":
            artifact_files.append(rel_path)
        else:
            source_files.append(rel_path)

        abs_path = repo_root / rel_path
        if abs_path.exists():
            size = abs_path.stat().st_size
            if size > max_file_bytes:
                oversize_files.append((rel_path, size))

    errors: list[str] = []

    if len(staged) > max_files and not allow_mixed:
        errors.append(
            f"Commit has {len(staged)} files (limit {max_files}). "
            "Slice into smaller commits."
        )

    if source_files and artifact_files and not allow_mixed:
        errors.append(
            "Mixed source + artifact commit detected.\n"
            "Split this into separate commits.\n"
            f"Source files:\n{_format_list(source_files)}\n"
            f"Artifact files:\n{_format_list(artifact_files)}"
        )

    if oversize_files and not allow_mixed:
        detail = "\n".join(
            f"  - {path} ({size / 1024:.1f} KB)" for path, size in oversize_files[:12]
        )
        errors.append(
            "Oversized staged file(s) detected.\n"
            f"{detail}\n"
            "Move generated outputs to ignored paths or split into a dedicated artifact commit."
        )

    if bad_source_names and not allow_mixed:
        errors.append(
            "Legacy-style source filenames detected.\n"
            "Archive old scripts instead of adding backup/tmp/copy variants.\n"
            f"Problem files:\n{_format_list(bad_source_names)}"
        )

    if CURVES_PRIMARY_FILE in staged and not allow_mixed:
        version_snapshots = [
            path
            for path in staged
            if path.startswith("CSV_data/restricted/versions/curves_") and path.endswith(".csv")
        ]
        missing_followups: list[str] = []
        if CURVES_MANIFEST_FILE not in staged:
            missing_followups.append(CURVES_MANIFEST_FILE)
        if CHANGELOG_FILE not in staged:
            missing_followups.append(CHANGELOG_FILE)
        if not version_snapshots:
            missing_followups.append("CSV_data/restricted/versions/curves_<version>.csv")
        if missing_followups:
            errors.append(
                "Curve changes must include versioning metadata.\n"
                "Stage a version snapshot, the manifest, and a changelog update.\n"
                f"Missing:\n{_format_list(missing_followups)}"
            )

    errors.extend(
        validate_protected_memory_changes(
            staged,
            approval_granted=os.getenv(MEMORY_WRITE_APPROVAL_ENV, "").strip() == "1",
        )
    )

    if errors:
        print("[commit-hygiene] Commit blocked:\n", file=sys.stderr)
        print("\n\n".join(errors), file=sys.stderr)
        print(
            "\nOverride only when intentional: set AUTOSNIPER_ALLOW_MIXED_COMMIT=1 for one commit.",
            file=sys.stderr,
        )
        return 1

    print(
        "[commit-hygiene] OK "
        f"(files={len(staged)}, source={len(source_files)}, artifact={len(artifact_files)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
