from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.data_loader import dataset_path
else:  # pragma: no cover
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.data_loader import dataset_path


STATIC_PATH = dataset_path("vehicle_static_details.csv")
CURVES_PATH = dataset_path("curves.csv")
DEFAULT_OUTPUT = Path("missing_curve_tags.csv")
IGNORED_TAG_VALUES = {"", "nan", "none"}


def _normalize_tag(value: object) -> str:
    return str(value or "").strip().lower()


def _load_required_csv(path: Path, required_columns: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required input file not found: {path}")

    df = pd.read_csv(path, low_memory=False)
    missing_columns = sorted(column for column in required_columns if column not in df.columns)
    if missing_columns:
        raise ValueError(f"{path} is missing required columns: {missing_columns}")
    return df


def _canonical_tag_report_frame(canonical_tags: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"canonical_tag": canonical_tags}).loc[
        lambda frame: ~frame["canonical_tag"].isin(IGNORED_TAG_VALUES)
    ]


def build_missing_curve_report(static_df: pd.DataFrame, curves_df: pd.DataFrame) -> pd.DataFrame:
    static_tags = static_df["canonical_tag"].map(_normalize_tag)
    curve_tags = curves_df["canonical_tag"].map(_normalize_tag)

    observed = (
        _canonical_tag_report_frame(static_tags)
        .assign(observed_rows=1)
        .groupby("canonical_tag", as_index=False)["observed_rows"]
        .sum()
    )

    covered_tags = {
        tag
        for tag in curve_tags.tolist()
        if tag not in IGNORED_TAG_VALUES
    }

    missing = observed[~observed["canonical_tag"].isin(covered_tags)].copy()
    missing = missing.sort_values(["observed_rows", "canonical_tag"], ascending=[False, True]).reset_index(drop=True)
    return missing


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report canonical tags in vehicle_static_details.csv that are missing from curves.csv.")
    parser.add_argument("--static", type=Path, default=STATIC_PATH, help="Path to vehicle_static_details.csv")
    parser.add_argument("--curves", type=Path, default=CURVES_PATH, help="Path to curves.csv")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Destination CSV for missing curve tags")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    static_df = _load_required_csv(args.static, {"canonical_tag"})
    curves_df = _load_required_csv(args.curves, {"canonical_tag"})

    report_df = build_missing_curve_report(static_df, curves_df)
    write_dataframe_csv_atomic(report_df, args.output, index=False)
    print(f"Wrote {len(report_df):,} missing curve tag rows to {args.output}")


if __name__ == "__main__":
    main()
