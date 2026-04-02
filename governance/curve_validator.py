from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.curves import CURVE_COLUMNS
    from shared.data_loader import dataset_path
else:  # pragma: no cover
    from shared.curves import CURVE_COLUMNS
    from shared.data_loader import dataset_path


DEFAULT_CURVES_PATH = dataset_path("curves.csv")
PRICE_COLUMNS = ("price_low", "price_mid", "price_high")


def _warning_row(
    warning_type: str,
    message: str,
    *,
    canonical_tag: object = "",
    anchor_year: object = "",
    km_bucket: object = "",
    column_name: str = "",
) -> dict[str, object]:
    return {
        "warning_type": warning_type,
        "canonical_tag": str(canonical_tag or "").strip(),
        "anchor_year": anchor_year,
        "km_bucket": km_bucket,
        "column_name": column_name,
        "message": message,
    }


def build_curve_warnings(curves_df: pd.DataFrame) -> pd.DataFrame:
    warnings: list[dict[str, object]] = []

    missing_schema_columns = [column for column in CURVE_COLUMNS if column not in curves_df.columns]
    if missing_schema_columns:
        warnings.append(
            _warning_row(
                "missing_schema_columns",
                f"curves.csv is missing expected columns: {missing_schema_columns}",
            )
        )
        return pd.DataFrame(warnings)

    working = curves_df[list(CURVE_COLUMNS)].copy()
    working["canonical_tag"] = working["canonical_tag"].astype(str).str.strip()

    blank_tag_rows = working[working["canonical_tag"] == ""]
    for index in blank_tag_rows.index.tolist():
        warnings.append(
            _warning_row(
                "missing_anchor",
                f"Row {index} has a blank canonical_tag.",
            )
        )

    for column in ("anchor_year", "km_bucket", *PRICE_COLUMNS):
        working[column] = pd.to_numeric(working[column], errors="coerce")

    missing_anchor_rows = working[working["anchor_year"].isna() | working["km_bucket"].isna()]
    for index, row in missing_anchor_rows.iterrows():
        missing_fields: list[str] = []
        if pd.isna(row["anchor_year"]):
            missing_fields.append("anchor_year")
        if pd.isna(row["km_bucket"]):
            missing_fields.append("km_bucket")
        warnings.append(
            _warning_row(
                "missing_anchor",
                f"Row {index} has missing/non-numeric anchor fields: {', '.join(missing_fields)}.",
                canonical_tag=row.get("canonical_tag", ""),
                anchor_year=row.get("anchor_year", ""),
                km_bucket=row.get("km_bucket", ""),
            )
        )

    for column_name in PRICE_COLUMNS:
        negative_rows = working[working[column_name] < 0]
        for _, row in negative_rows.iterrows():
            warnings.append(
                _warning_row(
                    "negative_price",
                    f"{column_name} is negative.",
                    canonical_tag=row.get("canonical_tag", ""),
                    anchor_year=row.get("anchor_year", ""),
                    km_bucket=row.get("km_bucket", ""),
                    column_name=column_name,
                )
            )

    monotonic_scope = working.dropna(subset=["canonical_tag", "anchor_year", "km_bucket", *PRICE_COLUMNS]).copy()
    if monotonic_scope.empty:
        return pd.DataFrame(warnings)

    for (canonical_tag, anchor_year), subset in monotonic_scope.groupby(["canonical_tag", "anchor_year"], sort=True):
        ordered = subset.sort_values("km_bucket")
        for column_name in PRICE_COLUMNS:
            previous_value: float | None = None
            previous_km: int | None = None
            for _, row in ordered.iterrows():
                current_value = float(row[column_name])
                current_km = int(row["km_bucket"])
                if previous_value is not None and current_value > previous_value:
                    warnings.append(
                        _warning_row(
                            "price_increases_with_km",
                            (
                                f"{column_name} increases from km {previous_km} ({int(previous_value)}) "
                                f"to km {current_km} ({int(current_value)})."
                            ),
                            canonical_tag=canonical_tag,
                            anchor_year=int(anchor_year),
                            km_bucket=current_km,
                            column_name=column_name,
                        )
                    )
                previous_value = current_value
                previous_km = current_km

    warning_columns = ["warning_type", "canonical_tag", "anchor_year", "km_bucket", "column_name", "message"]
    warning_df = pd.DataFrame(warnings, columns=warning_columns)
    if warning_df.empty:
        return warning_df
    return warning_df.sort_values(
        by=["warning_type", "canonical_tag", "anchor_year", "km_bucket", "column_name", "message"],
        ascending=[True, True, True, True, True, True],
    ).reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate curves.csv and emit warnings without modifying any curve data.")
    parser.add_argument("--curves", type=Path, default=DEFAULT_CURVES_PATH, help="Path to curves.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.curves.exists():
        print(f"WARNING: curves.csv not found: {args.curves}")
        return

    curves_df = pd.read_csv(args.curves, low_memory=False)
    warnings_df = build_curve_warnings(curves_df)
    if warnings_df.empty:
        print("No curve warnings detected.")
        return

    for _, row in warnings_df.iterrows():
        print(
            "WARNING: "
            f"{row['warning_type']} | "
            f"tag={row['canonical_tag']} | "
            f"year={row['anchor_year']} | "
            f"km={row['km_bucket']} | "
            f"column={row['column_name']} | "
            f"{row['message']}"
        )
    print(f"Total warnings: {len(warnings_df):,}")


if __name__ == "__main__":
    main()
