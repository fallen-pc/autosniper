from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import dataset_path
    from shared.schema import ACTIVE_DETAIL_SCHEMA, STATE_TABLE_SCHEMA, STATIC_CANONICAL_SCHEMA, STATIC_VEHICLE_SCHEMA
    from scripts.extract_vehicle_details import (
        _prepare_normalised_snapshot,
        atomic_write,
        merge_and_save_static,
        seed_active_dataset,
    )
else:  # pragma: no cover
    from shared.data_loader import dataset_path
    from shared.schema import ACTIVE_DETAIL_SCHEMA, STATE_TABLE_SCHEMA, STATIC_CANONICAL_SCHEMA, STATIC_VEHICLE_SCHEMA
    from scripts.extract_vehicle_details import (
        _prepare_normalised_snapshot,
        atomic_write,
        merge_and_save_static,
        seed_active_dataset,
    )


RAW_PATH = dataset_path("raw_vehicle_data.csv")
NORMAL_PATH = dataset_path("normalised_data.csv")
STATIC_PATH = dataset_path("vehicle_static_details.csv")
ACTIVE_PATH = dataset_path("active_vehicle_details.csv")
MATCHED_PATH = dataset_path("matched_canonical_details.csv")
UNMATCHED_PATH = dataset_path("unmatched_canonical_details.csv")
STATE_PATH = dataset_path("vehicle_state.csv")
ALL_LINKS_PATH = dataset_path("all_vehicle_links.csv")
ACTIVE_LINKS_PATH = dataset_path("active_vehicle_links.csv")
EXCLUDED_PATH = dataset_path("excluded_listings.csv")
SOLD_PATH = dataset_path("sold_cars.csv")
REFERRED_PATH = dataset_path("referred_cars.csv")
STATIC_OUTPUT_COLUMNS = list(STATIC_CANONICAL_SCHEMA)


def _empty_csv(path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(pd.DataFrame(columns=columns), path)


def _read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except (ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def _coerce_schema(path: Path, columns: list[str]) -> dict[str, object]:
    before_exists = path.exists()
    before_df = _read_csv_safe(path)
    before_columns = list(before_df.columns)
    row_count = int(len(before_df))
    if before_df.empty:
        out_df = pd.DataFrame(columns=columns)
    else:
        out_df = before_df.copy()
        for column in columns:
            if column not in out_df.columns:
                out_df[column] = ""
        out_df = out_df.reindex(columns=columns)
    changed = (not before_exists) or (before_columns != columns)
    if changed:
        atomic_write(out_df, path)
    return {
        "path": str(path),
        "rows": row_count,
        "changed": changed,
        "before_columns": before_columns,
        "after_columns": columns,
    }


def _completed_url_set() -> set[str]:
    completed: set[str] = set()
    for path in (SOLD_PATH, REFERRED_PATH):
        df = _read_csv_safe(path)
        if df.empty or "url" not in df.columns:
            continue
        urls = (
            df["url"]
            .dropna()
            .astype(str)
            .str.strip()
            .str.lower()
        )
        completed.update(url for url in urls if url)
    return completed


def audit_and_lock_schemas() -> dict[str, dict[str, object]]:
    reports = {
        "raw_vehicle_data.csv": _coerce_schema(RAW_PATH, list(STATIC_VEHICLE_SCHEMA)),
        "normalised_data.csv": _coerce_schema(NORMAL_PATH, list(STATIC_VEHICLE_SCHEMA)),
        "vehicle_static_details.csv": _coerce_schema(STATIC_PATH, STATIC_OUTPUT_COLUMNS),
        "matched_canonical_details.csv": _coerce_schema(MATCHED_PATH, STATIC_OUTPUT_COLUMNS),
        "unmatched_canonical_details.csv": _coerce_schema(UNMATCHED_PATH, STATIC_OUTPUT_COLUMNS),
        "active_vehicle_details.csv": _coerce_schema(ACTIVE_PATH, list(ACTIVE_DETAIL_SCHEMA)),
        "vehicle_state.csv": _coerce_schema(STATE_PATH, list(STATE_TABLE_SCHEMA)),
    }
    for name, report in reports.items():
        status = "LOCKED" if report["changed"] else "OK"
        print(f"{name}: {status} ({report['rows']} rows)")
        if report["changed"]:
            print(f"  before: {report['before_columns']}")
            print(f"  after:  {report['after_columns']}")
    return reports


def normalize_from_raw() -> None:
    if not RAW_PATH.exists():
        print(f"Missing raw dataset: {RAW_PATH}")
        return
    raw_df = pd.read_csv(RAW_PATH)
    raw_df = raw_df.reindex(columns=STATIC_VEHICLE_SCHEMA, fill_value="")
    if raw_df.empty:
        print("Raw dataset is empty; nothing to normalize.")
        return
    normalized = _prepare_normalised_snapshot(raw_df)
    atomic_write(normalized, NORMAL_PATH)
    print(f"Normalised rows: {len(normalized)} written to {NORMAL_PATH}")


def apply_exclusions_from_normalised() -> None:
    if not NORMAL_PATH.exists():
        print(f"Missing normalised dataset: {NORMAL_PATH}")
        return
    normal_df = pd.read_csv(NORMAL_PATH)
    normal_df = normal_df.reindex(columns=STATIC_VEHICLE_SCHEMA, fill_value="")
    if normal_df.empty:
        print("Normalised dataset is empty; nothing to filter.")
        return
    completed_urls = _completed_url_set()
    if completed_urls and "url" in normal_df.columns:
        before = len(normal_df)
        normal_df = normal_df[
            ~normal_df["url"].fillna("").astype(str).str.strip().str.lower().isin(completed_urls)
        ].copy()
        removed = before - len(normal_df)
        if removed:
            print(
                f"Skipped {removed} completed sold/referred row(s) from normalised data before static merge."
            )
    existing_static = pd.read_csv(STATIC_PATH) if STATIC_PATH.exists() else pd.DataFrame()
    static_df = merge_and_save_static(existing_static, normal_df)
    seed_active_dataset(static_df)
    print(f"Static export refreshed from {NORMAL_PATH}")


def match_canonical_details() -> None:
    if not STATIC_PATH.exists():
        print(f"Missing static dataset: {STATIC_PATH}")
        return
    static_df = pd.read_csv(STATIC_PATH)
    if static_df.empty:
        print("Static dataset is empty; nothing to match.")
        return
    curves_path = dataset_path("curves.csv")
    if not curves_path.exists():
        print(f"Missing curves dataset: {curves_path}")
        return
    curves_df = pd.read_csv(curves_path)
    if "canonical_tag" not in curves_df.columns:
        print("curves.csv has no canonical_tag column; aborting.")
        return
    available_tags = (
        curves_df["canonical_tag"]
        .dropna()
        .astype(str)
        .str.strip()
        .replace({"nan": "", "None": ""})
    )
    allowed = {tag for tag in available_tags.tolist() if tag}
    if "canonical_tag" not in static_df.columns:
        static_df["canonical_tag"] = ""
    static_df["canonical_tag"] = (
        static_df["canonical_tag"].fillna("").astype(str).str.strip()
    )
    matched = static_df[static_df["canonical_tag"].isin(allowed)].copy()
    unmatched = static_df[~static_df["canonical_tag"].isin(allowed)].copy()
    atomic_write(matched, MATCHED_PATH)
    atomic_write(unmatched, UNMATCHED_PATH)
    print(
        f"Matched canonical tags: {len(matched)} rows -> {MATCHED_PATH}. "
        f"Unmatched: {len(unmatched)} rows -> {UNMATCHED_PATH}."
    )


def clear_pipeline() -> None:
    _empty_csv(ALL_LINKS_PATH, ["url", "discovered_at"])
    _empty_csv(ACTIVE_LINKS_PATH, ["url"])
    _empty_csv(RAW_PATH, list(STATIC_VEHICLE_SCHEMA))
    _empty_csv(NORMAL_PATH, list(STATIC_VEHICLE_SCHEMA))
    static_cols = list(STATIC_CANONICAL_SCHEMA)
    _empty_csv(STATIC_PATH, static_cols)
    active_cols = list(ACTIVE_DETAIL_SCHEMA)
    _empty_csv(ACTIVE_PATH, active_cols)
    _empty_csv(STATE_PATH, list(STATE_TABLE_SCHEMA))
    _empty_csv(EXCLUDED_PATH, ["timestamp", "url", "reason_code", "field_snapshot"])
    _empty_csv(MATCHED_PATH, static_cols)
    _empty_csv(UNMATCHED_PATH, static_cols)
    print("Pipeline cleared: links, raw, normalised, static, state, active, exclusions.")
    audit_and_lock_schemas()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run individual Grays pipeline stages.")
    parser.add_argument(
        "stage",
        choices=["normalize", "exclude", "match", "clear", "audit"],
        help="Pipeline stage to run",
    )
    args = parser.parse_args()

    if args.stage == "normalize":
        normalize_from_raw()
    elif args.stage == "exclude":
        apply_exclusions_from_normalised()
    elif args.stage == "match":
        match_canonical_details()
    elif args.stage == "clear":
        clear_pipeline()
    elif args.stage == "audit":
        audit_and_lock_schemas()


if __name__ == "__main__":
    main()
