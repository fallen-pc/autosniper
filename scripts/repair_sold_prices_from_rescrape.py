"""Create a repaired sold CSV preview from trusted re-scraped sold rows."""

from __future__ import annotations

import argparse
import re
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


DEFAULT_SOURCE = dataset_path("sold_cars.csv")
DEFAULT_REBUILT = dataset_path("sold_cars_rescraped.csv")
DEFAULT_REPORT = dataset_path("archives/sold_price_repair_report.csv")
DEFAULT_OUTPUT = dataset_path("archives/sold_cars_repaired_preview.csv")


def _normalize_url(value: object) -> str:
    return str(value or "").strip().casefold()


def parse_price(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    digits = re.sub(r"[^0-9.]", "", str(value))
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _prices_differ(left: object, right: object) -> bool:
    left_price = parse_price(left)
    right_price = parse_price(right)
    if left_price is None or right_price is None:
        return left_price != right_price
    return abs(left_price - right_price) > 0.01


def _format_price(value: object) -> str:
    parsed = parse_price(value)
    if parsed is None:
        return "" if value is None else str(value)
    return str(int(round(parsed)))


def _build_report_row(
    *,
    source_idx: int,
    source_len: int,
    original: pd.Series,
    rebuilt: pd.Series,
) -> dict[str, object]:
    old_price = original.get("price", "")
    new_price = rebuilt.get("price", "")
    old_numeric = parse_price(old_price)
    new_numeric = parse_price(new_price)
    diff = None
    if old_numeric is not None and new_numeric is not None:
        diff = new_numeric - old_numeric
    return {
        "source_pos": source_idx,
        "source_from_end": source_len - 1 - source_idx,
        "chunk_from_end": ((source_len - 1 - source_idx) // 100) * 100,
        "url": original.get("url", ""),
        "year": original.get("year", ""),
        "make": original.get("make", ""),
        "model": original.get("model", ""),
        "variant": original.get("variant", ""),
        "old_price": old_price,
        "new_price": new_price,
        "price_delta": "" if diff is None else int(round(diff)),
        "old_date_sold": original.get("date_sold", ""),
        "new_date_sold": rebuilt.get("date_sold", ""),
        "old_bids": original.get("bids", ""),
        "new_bids": rebuilt.get("bids", ""),
    }


def build_repair_preview(
    source_df: pd.DataFrame,
    rebuilt_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "url" not in source_df.columns:
        raise ValueError("source sold CSV must include url")
    if "url" not in rebuilt_df.columns:
        raise ValueError("rebuilt sold CSV must include url")

    repaired = source_df.copy().astype("object")
    source_norm = source_df["url"].map(_normalize_url)
    rebuilt = rebuilt_df.copy()
    rebuilt["_url_norm"] = rebuilt["url"].map(_normalize_url)
    rebuilt = rebuilt[rebuilt["_url_norm"].ne("")].drop_duplicates(subset=["_url_norm"], keep="last")
    rebuilt_lookup = rebuilt.set_index("_url_norm")

    report_rows: list[dict[str, object]] = []
    common_update_columns = [
        column
        for column in rebuilt_df.columns
        if column in repaired.columns and column not in {"url"}
    ]

    for idx, norm_url in source_norm.items():
        if not norm_url or norm_url not in rebuilt_lookup.index:
            continue
        original = repaired.loc[idx]
        rebuilt_row = rebuilt_lookup.loc[norm_url]
        if isinstance(rebuilt_row, pd.DataFrame):
            rebuilt_row = rebuilt_row.iloc[-1]
        if parse_price(rebuilt_row.get("price", "")) is None:
            continue
        if not _prices_differ(original.get("price", ""), rebuilt_row.get("price", "")):
            continue

        report_rows.append(
            _build_report_row(
                source_idx=int(idx),
                source_len=len(source_df),
                original=original,
                rebuilt=rebuilt_row,
            )
        )
        for column in common_update_columns:
            value = rebuilt_row.get(column, "")
            if pd.isna(value):
                continue
            repaired.at[idx, column] = value

        if "price_numeric" in repaired.columns:
            repaired.at[idx, "price_numeric"] = parse_price(rebuilt_row.get("price", ""))
        if "price_text" in repaired.columns:
            repaired.at[idx, "price_text"] = rebuilt_row.get("price", "")
        if "bids_numeric" in repaired.columns:
            repaired.at[idx, "bids_numeric"] = parse_price(rebuilt_row.get("bids", ""))

    report = pd.DataFrame(report_rows)
    if not report.empty:
        report = report.sort_values(["source_from_end", "url"], ascending=[True, True]).reset_index(drop=True)
    return repaired, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a sold CSV repair preview from re-scraped sold rows.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--rebuilt", type=Path, default=DEFAULT_REBUILT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source_df = pd.read_csv(args.source, low_memory=False)
    rebuilt_df = pd.read_csv(args.rebuilt, low_memory=False)
    repaired, report = build_repair_preview(source_df, rebuilt_df)

    write_dataframe_csv_atomic(report, args.report, index=False)
    write_dataframe_csv_atomic(repaired, args.output, index=False)

    print(f"Compared {len(rebuilt_df)} rebuilt rows against {len(source_df)} source rows.")
    print(f"Price repairs proposed: {len(report)}")
    print(f"Report written to {args.report}")
    print(f"Repaired preview written to {args.output}")


if __name__ == "__main__":
    main()
