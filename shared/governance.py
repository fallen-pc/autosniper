"""Governance checks and reporting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable

import pandas as pd
import yaml

from shared.canonical_tagging import UNCLASSIFIED
from shared.curves import (
    CURVE_COLUMNS,
    detect_legacy_columns,
    list_curve_tags,
    resolve_curve_canonical_tag,
    validate_curve_columns,
)
from shared.curve_versioning import latest_prior_curve_snapshot
from shared.data_loader import dataset_path
from shared.schema import (
    ACTIVE_DETAIL_SCHEMA,
    REFERRED_LISTING_SCHEMA,
    STATE_TABLE_SCHEMA,
    STATIC_CANONICAL_SCHEMA,
    STATIC_VEHICLE_SCHEMA,
)


RESTRICTED_GROUP_MAP_SCHEMA: list[str] = ["url", "canonical_tag", "reason_code", "source"]
SOLD_DETAIL_SCHEMA: list[str] = [
    "year",
    "make",
    "model",
    "variant",
    "body_type",
    "transmission",
    "fuel_type",
    "odometer_reading",
    "no_of_seats",
    "vin",
    "rego_no",
    "rego_expiry",
    "no_of_cylinders",
    "engine_capacity",
    "exterior_colour",
    "interior_colour",
    "key",
    "spare_key",
    "owners_manual",
    "service_history",
    "engine_turns_over",
    "location",
    "url",
    "general_condition",
    "bids",
    "price",
    "date_sold",
    "odo_suspect",
    "canonical_tag",
    "canonical_reason",
    "price_numeric",
    "price_text",
    "bids_numeric",
]

TRACKED_DATASET_PATHS: tuple[str, ...] = (
    "CSV_data/scrapers/all_vehicle_links.csv",
    "CSV_data/scrapers/active_vehicle_links.csv",
    "CSV_data/scrapers/raw_vehicle_data.csv",
    "CSV_data/scrapers/normalised_data.csv",
    "CSV_data/scrapers/excluded_listings.csv",
    "CSV_data/scrapers/pipeline_exclusions.csv",
    "CSV_data/scrapers/vehicle_static_details.csv",
    "CSV_data/scrapers/matched_canonical_details.csv",
    "CSV_data/scrapers/unmatched_canonical_details.csv",
    "CSV_data/scrapers/active_vehicle_details.csv",
    "CSV_data/scrapers/sold_cars.csv",
    "CSV_data/scrapers/referred_cars.csv",
    "CSV_data/restricted/restricted_group_map.csv",
    "CSV_data/restricted/curves.csv",
)

SCHEMA_CONTRACT_LOCK_PATH = (
    Path(__file__).resolve().parents[1]
    / "project_memory"
    / "01_machine_rules"
    / "dataset_contracts.yaml"
)
SCHEMA_AUTHORITY_PATHS: tuple[str, ...] = (
    "shared/schema.py",
    "project_memory/01_machine_rules/dataset_contracts.yaml",
)

IGNORED_CANONICAL_TAGS = {"", "nan", "none", UNCLASSIFIED.lower(), UNCLASSIFIED.upper().lower()}


@dataclass(frozen=True)
class DatasetContract:
    filename: str
    columns: tuple[str, ...]
    mode: str = "exact"


DATASET_CONTRACTS: tuple[DatasetContract, ...] = (
    DatasetContract("raw_vehicle_data.csv", tuple(STATIC_VEHICLE_SCHEMA)),
    DatasetContract("normalised_data.csv", tuple(STATIC_VEHICLE_SCHEMA)),
    DatasetContract("vehicle_static_details.csv", tuple(STATIC_CANONICAL_SCHEMA)),
    DatasetContract("matched_canonical_details.csv", tuple(STATIC_CANONICAL_SCHEMA)),
    DatasetContract("unmatched_canonical_details.csv", tuple(STATIC_CANONICAL_SCHEMA)),
    DatasetContract("vehicle_state.csv", tuple(STATE_TABLE_SCHEMA)),
    DatasetContract("active_vehicle_details.csv", tuple(ACTIVE_DETAIL_SCHEMA)),
    DatasetContract("sold_cars.csv", tuple(SOLD_DETAIL_SCHEMA)),
    DatasetContract("referred_cars.csv", tuple(REFERRED_LISTING_SCHEMA)),
    DatasetContract("restricted_group_map.csv", tuple(RESTRICTED_GROUP_MAP_SCHEMA)),
    DatasetContract("curves.csv", tuple(CURVE_COLUMNS)),
)


def _normalize_path(value: str | Path) -> str:
    return str(value).replace("\\", "/").strip()


def _normalize_tag(value: object) -> str:
    text = "" if value is None else str(value).strip().lower()
    return "" if text in IGNORED_CANONICAL_TAGS else text


def _read_columns(path: Path) -> list[str]:
    try:
        return list(pd.read_csv(path, nrows=0).columns)
    except pd.errors.EmptyDataError:
        return []


def validate_dataset_contracts() -> list[str]:
    errors: list[str] = []
    for contract in DATASET_CONTRACTS:
        path = dataset_path(contract.filename)
        if not path.exists():
            errors.append(f"Missing governed dataset: {contract.filename} ({path})")
            continue
        columns = _read_columns(path)
        expected = list(contract.columns)
        if columns != expected:
            missing = [column for column in expected if column not in columns]
            unexpected = [column for column in columns if column not in expected]
            errors.append(
                f"{contract.filename} schema mismatch; missing={missing or '[]'} "
                f"unexpected={unexpected or '[]'}"
            )
    return errors


def validate_schema_contract_lock(path: Path = SCHEMA_CONTRACT_LOCK_PATH) -> list[str]:
    """Require code-backed dataset contracts to match the protected schema lock."""
    if not path.exists():
        return [f"Missing protected schema contract lock: {path}"]
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return [f"Could not read protected schema contract lock {path}: {exc}"]

    locked_datasets = payload.get("datasets")
    if not isinstance(locked_datasets, dict):
        return [f"Protected schema contract lock has no datasets mapping: {path}"]

    current = {
        contract.filename: {
            "mode": contract.mode,
            "columns": list(contract.columns),
        }
        for contract in DATASET_CONTRACTS
    }
    locked = {
        str(filename): {
            "mode": str(spec.get("mode", "")),
            "columns": list(spec.get("columns", [])),
        }
        for filename, spec in locked_datasets.items()
        if isinstance(spec, dict)
    }
    if current == locked:
        return []

    missing = sorted(set(locked) - set(current))
    unexpected = sorted(set(current) - set(locked))
    changed = sorted(
        filename
        for filename in set(current) & set(locked)
        if current[filename] != locked[filename]
    )
    return [
        "Code-backed dataset schemas differ from the protected schema contract lock; "
        f"missing={missing or []} unexpected={unexpected or []} changed={changed or []}. "
        "Schema migrations require an explicit protected lock update and approval."
    ]


def validate_schema_authority_changes(
    changed_paths: Iterable[str | Path],
    *,
    approval_granted: bool,
) -> list[str]:
    """Block schema-authority edits unless a dedicated migration approval is present."""
    changed = sorted({_normalize_path(path) for path in changed_paths})
    protected = [path for path in changed if path in SCHEMA_AUTHORITY_PATHS]
    if not protected or approval_granted:
        return []
    return [
        "Schema authority changes require explicit approval via the "
        "schema-migration-approved PR label: " + ", ".join(protected)
    ]


def validate_curve_table(curves_df: pd.DataFrame) -> list[str]:
    errors: list[str] = []

    try:
        detect_legacy_columns(curves_df)
        validate_curve_columns(curves_df)
    except (RuntimeError, ValueError) as exc:
        errors.append(str(exc))
        return errors

    if curves_df.empty:
        errors.append("curves.csv is empty.")
        return errors

    working = curves_df.copy()
    working["canonical_tag"] = working["canonical_tag"].astype(str).str.strip()
    if (working["canonical_tag"] == "").any():
        errors.append("curves.csv contains blank canonical_tag values.")

    numeric_columns = ["anchor_year", "km_bucket", "price_low", "price_mid", "price_high"]
    for column in numeric_columns:
        working[column] = pd.to_numeric(working[column], errors="coerce")
        if working[column].isna().any():
            errors.append(f"curves.csv contains non-numeric values in {column}.")

    if errors:
        return errors

    duplicate_mask = working.duplicated(subset=["canonical_tag", "anchor_year", "km_bucket"], keep=False)
    if duplicate_mask.any():
        sample = working.loc[duplicate_mask, ["canonical_tag", "anchor_year", "km_bucket"]].head(5)
        errors.append(f"curves.csv contains duplicate curve keys: {sample.to_dict(orient='records')}")

    invalid_band_mask = (
        (working["price_low"] > working["price_mid"]) | (working["price_mid"] > working["price_high"])
    )
    if invalid_band_mask.any():
        sample = working.loc[
            invalid_band_mask,
            ["canonical_tag", "anchor_year", "km_bucket", "price_low", "price_mid", "price_high"],
        ].head(5)
        errors.append(f"curves.csv contains invalid price bands: {sample.to_dict(orient='records')}")

    monotonicity_df = build_curve_monotonicity_report(working)
    if not monotonicity_df.empty:
        hard_failures = monotonicity_df[monotonicity_df["severity"] == "error"]
        errors.extend(hard_failures["message"].dropna().astype(str).tolist())
    return errors


def validate_curves_dataset() -> list[str]:
    curves_path = dataset_path("curves.csv")
    if not curves_path.exists():
        return [f"Missing governed dataset: curves.csv ({curves_path})"]
    curves_df = pd.read_csv(curves_path)
    errors = validate_curve_table(curves_df)
    errors.extend(validate_curve_monotonicity_baseline(curves_path, curves_df))
    return errors


def build_curve_coverage_report(
    static_df: pd.DataFrame | None,
    restricted_group_map_df: pd.DataFrame | None,
    curves_df: pd.DataFrame | None,
) -> pd.DataFrame:
    observed_frames: list[pd.DataFrame] = []

    if static_df is not None and not static_df.empty and "canonical_tag" in static_df.columns:
        static_tags = pd.DataFrame(
            {
                "canonical_tag": static_df["canonical_tag"].map(_normalize_tag),
                "source": "static",
            }
        )
        observed_frames.append(static_tags)

    if (
        restricted_group_map_df is not None
        and not restricted_group_map_df.empty
        and "canonical_tag" in restricted_group_map_df.columns
    ):
        source_series = restricted_group_map_df.get("source", pd.Series("", index=restricted_group_map_df.index))
        group_tags = pd.DataFrame(
            {
                "canonical_tag": restricted_group_map_df["canonical_tag"].map(_normalize_tag),
                "source": source_series.fillna("").astype(str).str.strip().replace("", "restricted_group_map"),
            }
        )
        observed_frames.append(group_tags)

    if observed_frames:
        observed = pd.concat(observed_frames, ignore_index=True)
        observed = observed[observed["canonical_tag"] != ""].copy()
    else:
        observed = pd.DataFrame(columns=["canonical_tag", "source"])

    curves_working = pd.DataFrame(columns=list(CURVE_COLUMNS))
    if curves_df is not None and not curves_df.empty:
        curves_working = curves_df.copy()
        curves_working["canonical_tag"] = curves_working["canonical_tag"].map(_normalize_tag)
        curves_working = curves_working[curves_working["canonical_tag"] != ""].copy()

    if observed.empty and curves_working.empty:
        return pd.DataFrame(
            columns=[
                "canonical_tag",
                "observed_rows",
                "static_rows",
                "group_map_rows",
                "sources",
                "has_curve",
                "curve_rows",
                "anchor_year_count",
                "anchor_years",
                "status",
            ]
        )

    observed_summary = (
        observed.assign(row_count=1)
        .groupby("canonical_tag", as_index=False)
        .agg(
            observed_rows=("row_count", "sum"),
            static_rows=("source", lambda values: int((pd.Series(values) == "static").sum())),
            group_map_rows=("source", lambda values: int((pd.Series(values) != "static").sum())),
            sources=("source", lambda values: ", ".join(sorted({value for value in values if value}))),
        )
    )

    curve_summary = pd.DataFrame(
        columns=["canonical_tag", "curve_rows", "anchor_year_count", "anchor_years"]
    )
    if not curves_working.empty:
        curve_summary = (
            curves_working.groupby("canonical_tag", as_index=False)
            .agg(
                curve_rows=("km_bucket", "size"),
                anchor_year_count=("anchor_year", lambda values: int(pd.Series(values).nunique())),
                anchor_years=(
                    "anchor_year",
                    lambda values: ", ".join(str(int(value)) for value in sorted(pd.Series(values).dropna().unique())),
                ),
            )
        )

    visible_curve_tags = list_curve_tags(curves_working)
    tag_index = pd.DataFrame(
        {
            "canonical_tag": sorted(
                set(observed_summary.get("canonical_tag", pd.Series(dtype=object)).tolist())
                | set(visible_curve_tags)
            )
        }
    )
    coverage = tag_index.merge(observed_summary, on="canonical_tag", how="left")
    coverage["resolved_curve_tag"] = coverage["canonical_tag"].map(resolve_curve_canonical_tag)
    coverage = coverage.merge(
        curve_summary,
        left_on="resolved_curve_tag",
        right_on="canonical_tag",
        how="left",
        suffixes=("", "_curve"),
    )
    if "canonical_tag_curve" in coverage.columns:
        coverage = coverage.drop(columns=["canonical_tag_curve"])
    for column in ("observed_rows", "static_rows", "group_map_rows", "curve_rows", "anchor_year_count"):
        coverage[column] = coverage[column].fillna(0).astype(int)
    for column in ("sources", "anchor_years"):
        coverage[column] = coverage[column].fillna("")
    coverage["has_curve"] = coverage["curve_rows"] > 0
    coverage["status"] = coverage["has_curve"].map({True: "covered", False: "missing_curve"})
    coverage = coverage.drop(columns=["resolved_curve_tag"])
    coverage = coverage.sort_values(
        by=["has_curve", "observed_rows", "canonical_tag"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
    return coverage


def summarize_curve_coverage(coverage_df: pd.DataFrame) -> dict[str, int]:
    if coverage_df is None or coverage_df.empty:
        return {
            "observed_tags": 0,
            "covered_tags": 0,
            "missing_tags": 0,
            "observed_rows_missing_curves": 0,
        }
    missing_df = coverage_df[~coverage_df["has_curve"]]
    return {
        "observed_tags": int(len(coverage_df)),
        "covered_tags": int(coverage_df["has_curve"].sum()),
        "missing_tags": int((~coverage_df["has_curve"]).sum()),
        "observed_rows_missing_curves": int(missing_df["observed_rows"].sum()),
    }


def render_curve_coverage_markdown(coverage_df: pd.DataFrame) -> str:
    summary = summarize_curve_coverage(coverage_df)
    lines = [
        "# Curve Coverage Report",
        "",
        f"- Observed canonical tags: {summary['observed_tags']}",
        f"- Tags with curves: {summary['covered_tags']}",
        f"- Tags missing curves: {summary['missing_tags']}",
        f"- Observed rows missing curves: {summary['observed_rows_missing_curves']}",
        "",
    ]

    missing_df = coverage_df[~coverage_df["has_curve"]].copy() if coverage_df is not None else pd.DataFrame()
    if missing_df.empty:
        lines.append("No canonical tags are missing curves.")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| canonical_tag | observed_rows | static_rows | group_map_rows | sources |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for _, row in missing_df.head(50).iterrows():
        lines.append(
            f"| {row['canonical_tag']} | {int(row['observed_rows'])} | {int(row['static_rows'])} | "
            f"{int(row['group_map_rows'])} | {row['sources']} |"
        )
    return "\n".join(lines) + "\n"


def build_curve_monotonicity_report(curves_df: pd.DataFrame | None) -> pd.DataFrame:
    columns = [
        "canonical_tag",
        "anchor_year",
        "km_bucket",
        "column_name",
        "issue_type",
        "severity",
        "message",
    ]
    if curves_df is None or curves_df.empty:
        return pd.DataFrame(columns=columns)

    working = curves_df.copy()
    for column in ("canonical_tag",):
        if column not in working.columns:
            return pd.DataFrame(columns=columns)
    numeric_columns = ["anchor_year", "km_bucket", "price_low", "price_mid", "price_high"]
    for column in numeric_columns:
        if column not in working.columns:
            return pd.DataFrame(columns=columns)
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working["canonical_tag"] = working["canonical_tag"].astype(str).str.strip()
    working = working.dropna(subset=["anchor_year", "km_bucket", "price_low", "price_mid", "price_high"])
    if working.empty:
        return pd.DataFrame(columns=columns)

    issues: list[dict[str, object]] = []
    price_columns = ("price_low", "price_mid", "price_high")

    for (canonical_tag, anchor_year), subset in working.groupby(["canonical_tag", "anchor_year"], sort=True):
        ordered = subset.sort_values("km_bucket")
        if not ordered["km_bucket"].is_unique:
            continue
        for column_name in price_columns:
            deltas = ordered[column_name].diff()
            problem_rows = ordered.loc[deltas > 0, ["km_bucket", column_name]]
            for idx in problem_rows.index.tolist():
                current_row = ordered.loc[idx]
                previous_idx = ordered.index.get_loc(idx) - 1
                previous_row = ordered.iloc[previous_idx]
                issues.append(
                    {
                        "canonical_tag": canonical_tag,
                        "anchor_year": int(anchor_year),
                        "km_bucket": int(current_row["km_bucket"]),
                        "column_name": column_name,
                        "issue_type": "km_increase",
                        "severity": "error",
                        "message": (
                            f"Curve drift detected for {canonical_tag}/{int(anchor_year)}: "
                            f"{column_name} increases from km {int(previous_row['km_bucket'])} "
                            f"({int(previous_row[column_name])}) to km {int(current_row['km_bucket'])} "
                            f"({int(current_row[column_name])})."
                        ),
                    }
                )

    for (canonical_tag, km_bucket), subset in working.groupby(["canonical_tag", "km_bucket"], sort=True):
        ordered = subset.sort_values("anchor_year")
        if not ordered["anchor_year"].is_unique:
            continue
        for column_name in price_columns:
            deltas = ordered[column_name].diff()
            problem_rows = ordered.loc[deltas < 0, ["anchor_year", column_name]]
            for idx in problem_rows.index.tolist():
                current_row = ordered.loc[idx]
                previous_idx = ordered.index.get_loc(idx) - 1
                previous_row = ordered.iloc[previous_idx]
                issues.append(
                    {
                        "canonical_tag": canonical_tag,
                        "anchor_year": int(current_row["anchor_year"]),
                        "km_bucket": int(km_bucket),
                        "column_name": column_name,
                        "issue_type": "year_reversal",
                        "severity": "warning",
                        "message": (
                            f"Anchor-year reversal for {canonical_tag}/km {int(km_bucket)}: "
                            f"{column_name} drops from year {int(previous_row['anchor_year'])} "
                            f"({int(previous_row[column_name])}) to year {int(current_row['anchor_year'])} "
                            f"({int(current_row[column_name])})."
                        ),
                    }
                )

    report_df = pd.DataFrame(issues, columns=columns)
    if report_df.empty:
        return report_df
    return report_df.sort_values(
        by=["severity", "canonical_tag", "anchor_year", "km_bucket", "column_name"],
        ascending=[True, True, True, True, True],
    ).reset_index(drop=True)


def summarize_curve_monotonicity(report_df: pd.DataFrame) -> dict[str, int]:
    if report_df is None or report_df.empty:
        return {"issues": 0, "errors": 0, "warnings": 0}
    severity = report_df["severity"].astype(str).str.lower()
    return {
        "issues": int(len(report_df)),
        "errors": int((severity == "error").sum()),
        "warnings": int((severity == "warning").sum()),
    }


def _monotonicity_issue_keys(report_df: pd.DataFrame) -> set[tuple[object, ...]]:
    if report_df is None or report_df.empty:
        return set()
    key_columns = ["canonical_tag", "anchor_year", "km_bucket", "column_name", "issue_type", "severity"]
    return {
        tuple(row[column] for column in key_columns)
        for _, row in report_df.loc[:, key_columns].iterrows()
    }


def summarize_monotonicity_regression(
    current_report_df: pd.DataFrame,
    baseline_report_df: pd.DataFrame,
) -> dict[str, int]:
    current_keys = _monotonicity_issue_keys(current_report_df)
    baseline_keys = _monotonicity_issue_keys(baseline_report_df)
    return {
        "current_issues": len(current_keys),
        "baseline_issues": len(baseline_keys),
        "new_issues": len(current_keys - baseline_keys),
        "resolved_issues": len(baseline_keys - current_keys),
    }


def validate_curve_monotonicity_baseline(
    curves_path: Path | None = None,
    curves_df: pd.DataFrame | None = None,
) -> list[str]:
    path = curves_path or dataset_path("curves.csv")
    baseline_path = latest_prior_curve_snapshot(path)
    if baseline_path is None:
        return []

    current_df = curves_df if curves_df is not None else pd.read_csv(path)
    baseline_df = pd.read_csv(baseline_path)
    current_report_df = build_curve_monotonicity_report(current_df)
    baseline_report_df = build_curve_monotonicity_report(baseline_df)
    current_keys = _monotonicity_issue_keys(current_report_df)
    baseline_keys = _monotonicity_issue_keys(baseline_report_df)
    new_issue_keys = sorted(current_keys - baseline_keys)
    if not new_issue_keys:
        return []

    sample = ", ".join(
        f"{canonical_tag}/{int(anchor_year)}/{int(km_bucket)}/{column_name}/{issue_type}"
        for canonical_tag, anchor_year, km_bucket, column_name, issue_type, _severity in new_issue_keys[:5]
    )
    return [
        (
            "Curve monotonicity regressed versus the previous versioned snapshot "
            f"({baseline_path.as_posix()}): {len(new_issue_keys)} new issues detected. "
            f"Sample: {sample}"
        )
    ]


def render_curve_monotonicity_markdown(report_df: pd.DataFrame) -> str:
    summary = summarize_curve_monotonicity(report_df)
    lines = [
        "# Curve Monotonicity Report",
        "",
        f"- Total issues: {summary['issues']}",
        f"- Errors: {summary['errors']}",
        f"- Warnings: {summary['warnings']}",
        "",
    ]
    if report_df is None or report_df.empty:
        lines.append("No monotonicity issues detected.")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| severity | issue_type | canonical_tag | anchor_year | km_bucket | column_name |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for _, row in report_df.head(100).iterrows():
        lines.append(
            f"| {row['severity']} | {row['issue_type']} | {row['canonical_tag']} | "
            f"{int(row['anchor_year'])} | {int(row['km_bucket'])} | {row['column_name']} |"
        )
    return "\n".join(lines) + "\n"


def _load_report_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def write_governance_report_bundle(report_dir: Path) -> dict[str, object]:
    static_df = _load_report_csv(dataset_path("vehicle_static_details.csv"))
    group_map_df = _load_report_csv(dataset_path("restricted_group_map.csv"))
    curves_df = _load_report_csv(dataset_path("curves.csv"))

    coverage_df = build_curve_coverage_report(static_df, group_map_df, curves_df)
    coverage_summary = summarize_curve_coverage(coverage_df)
    monotonicity_df = build_curve_monotonicity_report(curves_df)
    monotonicity_summary = summarize_curve_monotonicity(monotonicity_df)

    report_dir.mkdir(parents=True, exist_ok=True)
    coverage_csv_path = report_dir / "curve_coverage.csv"
    coverage_md_path = report_dir / "curve_coverage.md"
    monotonicity_csv_path = report_dir / "curve_monotonicity.csv"
    monotonicity_md_path = report_dir / "curve_monotonicity.md"

    coverage_df.to_csv(coverage_csv_path, index=False)
    coverage_md_path.write_text(render_curve_coverage_markdown(coverage_df), encoding="utf-8")
    monotonicity_df.to_csv(monotonicity_csv_path, index=False)
    monotonicity_md_path.write_text(render_curve_monotonicity_markdown(monotonicity_df), encoding="utf-8")

    return {
        "coverage_summary": coverage_summary,
        "monotonicity_summary": monotonicity_summary,
        "paths": {
            "coverage_csv": coverage_csv_path,
            "coverage_md": coverage_md_path,
            "monotonicity_csv": monotonicity_csv_path,
            "monotonicity_md": monotonicity_md_path,
        },
    }


def classify_dataset_deltas(
    changed_paths: Iterable[str | Path],
    *,
    allowed_patterns: Iterable[str] = (),
) -> dict[str, list[str]]:
    normalized_paths = sorted({_normalize_path(path) for path in changed_paths if str(path).strip()})
    tracked = [path for path in normalized_paths if path in TRACKED_DATASET_PATHS]
    allowed = []
    unexpected = []
    patterns = [_normalize_path(pattern) for pattern in allowed_patterns if str(pattern).strip()]
    for path in tracked:
        if any(fnmatch(path, pattern) for pattern in patterns):
            allowed.append(path)
        else:
            unexpected.append(path)
    return {
        "tracked": tracked,
        "allowed": allowed,
        "unexpected": unexpected,
    }
