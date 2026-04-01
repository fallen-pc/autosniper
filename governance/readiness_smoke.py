"""Non-mutating readiness checks for datasets and scheduled entrypoints."""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.csv_utils import read_csv_or_empty
    from shared.data_loader import dataset_path
else:  # pragma: no cover
    from shared.csv_utils import read_csv_or_empty
    from shared.data_loader import dataset_path


REQUIRED_DATASETS = (
    "all_vehicle_links.csv",
    "active_vehicle_links.csv",
    "raw_vehicle_data.csv",
    "normalised_data.csv",
    "vehicle_static_details.csv",
    "vehicle_state.csv",
    "active_vehicle_details.csv",
    "sold_cars.csv",
    "referred_cars.csv",
    "restricted_group_map.csv",
    "curves.csv",
)

ENTRYPOINT_IMPORTS = (
    "scripts.extract_links",
    "scripts.extract_vehicle_details",
    "scripts.update_bids",
    "scripts.update_master",
    "scripts.run_grays_pipeline_loop",
    "governance.run_checks",
)

CLI_HELP_TARGETS = (
    "scripts/extract_vehicle_details.py",
    "scripts/update_bids.py",
    "scripts/run_grays_pipeline_loop.py",
    "scripts/governance_checks.py",
)


def load_required_datasets(dataset_names: tuple[str, ...] = REQUIRED_DATASETS) -> dict[str, pd.DataFrame]:
    return {name: read_csv_or_empty(dataset_path(name)) for name in dataset_names}


def _normalized_url_set(df: pd.DataFrame) -> set[str]:
    if df is None or df.empty or "url" not in df.columns:
        return set()
    return {
        value
        for value in df["url"].fillna("").astype(str).str.strip().tolist()
        if value
    }


def _duplicate_url_error(df: pd.DataFrame, label: str) -> list[str]:
    if df is None or df.empty or "url" not in df.columns:
        return []
    normalized = df["url"].fillna("").astype(str).str.strip()
    duplicates = normalized[normalized != ""]
    duplicates = duplicates[duplicates.duplicated(keep=False)]
    if duplicates.empty:
        return []
    sample = ", ".join(sorted(set(duplicates.tolist()))[:5])
    return [f"{label} contains duplicate url rows. Sample: {sample}"]


def validate_materialized_views(datasets: dict[str, pd.DataFrame]) -> list[str]:
    errors: list[str] = []

    static_df = datasets.get("vehicle_static_details.csv", pd.DataFrame())
    state_df = datasets.get("vehicle_state.csv", pd.DataFrame())
    active_df = datasets.get("active_vehicle_details.csv", pd.DataFrame())
    active_links_df = datasets.get("active_vehicle_links.csv", pd.DataFrame())

    errors.extend(_duplicate_url_error(static_df, "vehicle_static_details.csv"))
    errors.extend(_duplicate_url_error(state_df, "vehicle_state.csv"))
    errors.extend(_duplicate_url_error(active_df, "active_vehicle_details.csv"))

    if state_df.empty or "state" not in state_df.columns:
        errors.append("vehicle_state.csv is missing data or has no state column.")
        return errors

    state_working = state_df.copy()
    state_working["state"] = state_working["state"].fillna("").astype(str).str.strip().str.lower()
    state_active_urls = _normalized_url_set(state_working[state_working["state"] == "active"])

    active_urls = _normalized_url_set(active_df)
    static_urls = _normalized_url_set(static_df)
    active_link_urls = _normalized_url_set(active_links_df)

    unexpected_active = sorted(active_urls - state_active_urls)
    if unexpected_active:
        errors.append(
            "active_vehicle_details.csv contains urls that are not active in vehicle_state.csv. "
            f"Sample: {', '.join(unexpected_active[:5])}"
        )

    missing_static = sorted(active_urls - static_urls)
    if missing_static:
        errors.append(
            "active_vehicle_details.csv references urls missing from vehicle_static_details.csv. "
            f"Sample: {', '.join(missing_static[:5])}"
        )

    if active_link_urls:
        stale_active = sorted(active_urls - active_link_urls)
        if stale_active:
            errors.append(
                "active_vehicle_details.csv contains urls missing from active_vehicle_links.csv. "
                f"Sample: {', '.join(stale_active[:5])}"
            )

    return errors


def validate_dataset_presence(dataset_names: tuple[str, ...] = REQUIRED_DATASETS) -> list[str]:
    errors: list[str] = []
    for name in dataset_names:
        path = dataset_path(name)
        if not path.exists():
            errors.append(f"Missing required dataset: {name} ({path})")
    return errors


def validate_entrypoint_imports(module_names: tuple[str, ...] = ENTRYPOINT_IMPORTS) -> list[str]:
    errors: list[str] = []
    for module_name in module_names:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Import failed for {module_name}: {exc}")
    return errors


def validate_cli_help(help_targets: tuple[str, ...] = CLI_HELP_TARGETS) -> list[str]:
    errors: list[str] = []
    for relative_target in help_targets:
        command = [sys.executable, relative_target, "--help"]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            errors.append(f"CLI help failed for {relative_target}: {stderr}")
    return errors


def run_readiness_checks() -> list[str]:
    errors = validate_dataset_presence()
    datasets = load_required_datasets()
    errors.extend(validate_materialized_views(datasets))
    errors.extend(validate_entrypoint_imports())
    errors.extend(validate_cli_help())
    return errors


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Run non-mutating readiness checks.")


def main() -> int:
    parser = build_parser()
    parser.parse_args()
    errors = run_readiness_checks()
    if errors:
        for error in errors:
            print(f"[readiness] ERROR: {error}", file=sys.stderr)
        return 1
    print("[readiness] all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
