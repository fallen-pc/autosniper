"""Generate a ranked curve-build queue from sold_cars.csv."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.canonical_tagging import UNCLASSIFIED, tag_dataframe
    from shared.curves import list_curve_tags, load_curves, resolve_curve_canonical_tag
    from shared.data_loader import dataset_path
    from shared.sold_cleaning import normalize_listing_fields
else:  # pragma: no cover
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.canonical_tagging import UNCLASSIFIED, tag_dataframe
    from shared.curves import list_curve_tags, load_curves, resolve_curve_canonical_tag
    from shared.data_loader import dataset_path
    from shared.sold_cleaning import normalize_listing_fields


DEFAULT_INPUT = dataset_path("sold_cars.csv")
DEFAULT_OUTPUT = dataset_path("quality/curve_candidates.csv")
OUTPUT_COLUMNS = [
    "generated_at",
    "curve_tag",
    "curve_exists",
    "recommended_action",
    "next_step",
    "next_after_curve",
    "ready_for_curve",
    "review_reason",
    "score",
    "priority_rank",
    "sold_count_total",
    "sold_count_usable",
    "numeric_coverage_pct",
    "canonical_tag_count",
    "source_canonical_tags",
    "member_badges",
    "make",
    "model",
    "fuel_type",
    "transmission",
    "body_type",
    "series",
    "year_min",
    "year_max",
    "year_span",
    "odometer_min",
    "odometer_median",
    "odometer_max",
    "odometer_std",
    "price_min",
    "price_median",
    "price_max",
    "price_std",
    "price_spread_pct",
    "passes_min_listings",
    "passes_year_span",
    "passes_odometer_variance",
    "autotrader_query",
    "source_dataset",
]


def _coerce_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _coalesce_numeric(frame: pd.DataFrame, candidates: list[str]) -> pd.Series:
    resolved = pd.Series(index=frame.index, dtype="float64")
    for column in candidates:
        if column not in frame.columns:
            continue
        series = _coerce_numeric(frame[column])
        resolved = resolved.fillna(series)
    return resolved


def _join_unique(values: pd.Series) -> str:
    unique = sorted({str(value).strip() for value in values.tolist() if str(value).strip()})
    return "|".join(unique)


def _parse_tag_parts(tag: str) -> dict[str, str]:
    parts = str(tag or "").strip().split("_")
    if len(parts) != 7:
        return {
            "make": "",
            "model": "",
            "badge": "",
            "fuel_type": "",
            "transmission": "",
            "body_type": "",
            "series": "",
        }
    return {
        "make": parts[0],
        "model": parts[1],
        "badge": parts[2],
        "fuel_type": parts[3],
        "transmission": parts[4],
        "body_type": parts[5],
        "series": parts[6],
    }


def _build_autotrader_query(parts: dict[str, str]) -> str:
    return " ".join(
        value
        for value in (
            parts.get("make", ""),
            parts.get("model", ""),
            parts.get("series", ""),
            parts.get("fuel_type", ""),
            parts.get("transmission", ""),
            parts.get("body_type", ""),
        )
        if value
    )


def load_tagged_sold_data(csv_path: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    sold_df = pd.read_csv(csv_path, low_memory=False)
    sold_df = normalize_listing_fields(sold_df)
    tagged_df = tag_dataframe(
        sold_df,
        source="sold",
        require_price=True,
        filter_unclassified=False,
        append_log=False,
    )
    canonical_series = (
        tagged_df["canonical_tag"]
        if "canonical_tag" in tagged_df.columns
        else pd.Series("", index=tagged_df.index, dtype="object")
    )
    tagged_df["canonical_tag"] = canonical_series.fillna("").astype(str).str.strip()
    tagged_df["curve_tag"] = tagged_df["canonical_tag"].apply(resolve_curve_canonical_tag)
    tagged_df["year_numeric"] = _coalesce_numeric(tagged_df, ["year"])
    tagged_df["price_numeric"] = _coalesce_numeric(tagged_df, ["price_numeric", "price"])
    tagged_df["odometer_numeric"] = _coalesce_numeric(
        tagged_df,
        ["odometer_numeric", "odometer_reading"],
    )

    stats = {
        "sold_rows": int(len(tagged_df)),
        "classified_rows": int((tagged_df["canonical_tag"] != UNCLASSIFIED).sum()),
        "unclassified_rows": int((tagged_df["canonical_tag"] == UNCLASSIFIED).sum()),
    }
    return tagged_df, stats


def build_curve_candidates(
    tagged_df: pd.DataFrame,
    *,
    curve_tags: set[str] | None = None,
    min_listings: int = 20,
    max_year_span: int = 6,
    min_odometer_std: float = 10000.0,
    generated_at: str | None = None,
) -> pd.DataFrame:
    if tagged_df is None or tagged_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    working = tagged_df.copy()
    canonical_series = (
        working["canonical_tag"]
        if "canonical_tag" in working.columns
        else pd.Series("", index=working.index, dtype="object")
    )
    working["canonical_tag"] = canonical_series.fillna("").astype(str).str.strip()
    if "curve_tag" not in working.columns:
        working["curve_tag"] = working["canonical_tag"].apply(resolve_curve_canonical_tag)
    working["curve_tag"] = working["curve_tag"].fillna("").astype(str).str.strip()

    working["year_numeric"] = _coalesce_numeric(working, ["year_numeric", "year"])
    working["price_numeric"] = _coalesce_numeric(working, ["price_numeric", "price"])
    working["odometer_numeric"] = _coalesce_numeric(
        working,
        ["odometer_numeric", "odometer_reading"],
    )

    usable_mask = (
        working["year_numeric"].notna()
        & working["price_numeric"].notna()
        & working["odometer_numeric"].notna()
    )
    working["is_usable"] = usable_mask

    valid = working[
        (working["canonical_tag"] != "")
        & (working["canonical_tag"] != UNCLASSIFIED)
        & (working["curve_tag"] != "")
    ].copy()
    if valid.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    live_curve_tags = {str(tag).strip() for tag in (curve_tags or set()) if str(tag).strip()}
    rows: list[dict[str, object]] = []
    timestamp = generated_at or pd.Timestamp.utcnow().isoformat()

    for curve_tag, group in valid.groupby("curve_tag", sort=True):
        usable = group[group["is_usable"]].copy()
        tag_parts = _parse_tag_parts(curve_tag)
        source_tags = _join_unique(group["canonical_tag"])
        member_badges = _join_unique(
            group["canonical_tag"].apply(lambda value: _parse_tag_parts(str(value)).get("badge", ""))
        )
        sold_count_total = int(len(group))
        sold_count_usable = int(len(usable))
        numeric_coverage_pct = sold_count_usable / sold_count_total if sold_count_total else 0.0

        review_reasons: list[str] = []
        if sold_count_usable < min_listings:
            review_reasons.append("low_sample_size")

        if usable.empty:
            review_reasons.extend(["missing_numeric_fields", "low_odometer_variance"])
            year_min = None
            year_max = None
            year_span = None
            odometer_min = None
            odometer_median = None
            odometer_max = None
            odometer_std = None
            price_min = None
            price_median = None
            price_max = None
            price_std = None
            price_spread_pct = None
            passes_year_span = False
            passes_odometer_variance = False
        else:
            year_min = int(usable["year_numeric"].min())
            year_max = int(usable["year_numeric"].max())
            year_span = int(year_max - year_min)
            if year_span > max_year_span:
                review_reasons.append("wide_year_span")

            odometer_min = float(usable["odometer_numeric"].min())
            odometer_median = float(usable["odometer_numeric"].median())
            odometer_max = float(usable["odometer_numeric"].max())
            odometer_std = float(usable["odometer_numeric"].std(ddof=0) or 0.0)
            if odometer_std < float(min_odometer_std):
                review_reasons.append("low_odometer_variance")

            price_min = float(usable["price_numeric"].min())
            price_median = float(usable["price_numeric"].median())
            price_max = float(usable["price_numeric"].max())
            price_std = float(usable["price_numeric"].std(ddof=0) or 0.0)
            if price_median and price_median > 0:
                price_spread_pct = float((price_max - price_min) / price_median)
            else:
                price_spread_pct = 0.0

            passes_year_span = year_span <= max_year_span
            passes_odometer_variance = odometer_std >= float(min_odometer_std)

        ready_for_curve = not review_reasons
        curve_exists = curve_tag in live_curve_tags

        if ready_for_curve:
            recommended_action = "refresh_curve" if curve_exists else "build_curve"
            next_step = "ai_curve_refresh" if curve_exists else "ai_curve_build"
            next_after_curve = "autotrader_scrape"
        else:
            recommended_action = "manual_review"
            next_step = "manual_review"
            next_after_curve = ""

        rows.append(
            {
                "generated_at": timestamp,
                "curve_tag": curve_tag,
                "curve_exists": curve_exists,
                "recommended_action": recommended_action,
                "next_step": next_step,
                "next_after_curve": next_after_curve,
                "ready_for_curve": ready_for_curve,
                "review_reason": "|".join(review_reasons),
                "sold_count_total": sold_count_total,
                "sold_count_usable": sold_count_usable,
                "numeric_coverage_pct": numeric_coverage_pct,
                "canonical_tag_count": len(source_tags.split("|")) if source_tags else 0,
                "source_canonical_tags": source_tags,
                "member_badges": member_badges,
                "make": tag_parts.get("make", ""),
                "model": tag_parts.get("model", ""),
                "fuel_type": tag_parts.get("fuel_type", ""),
                "transmission": tag_parts.get("transmission", ""),
                "body_type": tag_parts.get("body_type", ""),
                "series": tag_parts.get("series", ""),
                "year_min": year_min,
                "year_max": year_max,
                "year_span": year_span,
                "odometer_min": odometer_min,
                "odometer_median": odometer_median,
                "odometer_max": odometer_max,
                "odometer_std": odometer_std,
                "price_min": price_min,
                "price_median": price_median,
                "price_max": price_max,
                "price_std": price_std,
                "price_spread_pct": price_spread_pct,
                "passes_min_listings": sold_count_usable >= min_listings,
                "passes_year_span": passes_year_span,
                "passes_odometer_variance": passes_odometer_variance,
                "autotrader_query": _build_autotrader_query(tag_parts),
                "source_dataset": "sold_cars.csv",
            }
        )

    candidates = pd.DataFrame(rows)
    if candidates.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    for column in ("sold_count_usable", "price_spread_pct", "year_max"):
        candidates[column] = pd.to_numeric(candidates[column], errors="coerce")

    count_rank = candidates["sold_count_usable"].rank(method="average", pct=True).fillna(0.0)
    spread_rank = candidates["price_spread_pct"].rank(method="average", pct=True).fillna(0.0)
    recency_rank = candidates["year_max"].rank(method="average", pct=True).fillna(0.0)
    candidates["score"] = ((count_rank * 0.5) + (spread_rank * 0.3) + (recency_rank * 0.2)) * 100.0
    candidates["score"] = candidates["score"].round(2)

    candidates = candidates.sort_values(
        by=["ready_for_curve", "score", "sold_count_usable", "curve_tag"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)
    candidates["priority_rank"] = range(1, len(candidates) + 1)

    numeric_columns = [
        "numeric_coverage_pct",
        "odometer_min",
        "odometer_median",
        "odometer_max",
        "odometer_std",
        "price_min",
        "price_median",
        "price_max",
        "price_std",
        "price_spread_pct",
        "score",
    ]
    for column in numeric_columns:
        if column in candidates.columns:
            candidates[column] = pd.to_numeric(candidates[column], errors="coerce").round(2)

    return candidates.reindex(columns=OUTPUT_COLUMNS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a ranked curve candidate queue from sold_cars.csv using canonical tags "
            "and existing curve aliases."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Path to sold_cars.csv")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination CSV for ranked curve candidates",
    )
    parser.add_argument(
        "--min-listings",
        type=int,
        default=20,
        help="Minimum usable sold rows required before a group is curve-ready",
    )
    parser.add_argument(
        "--max-year-span",
        type=int,
        default=6,
        help="Maximum allowed year spread within a candidate group",
    )
    parser.add_argument(
        "--min-odometer-std",
        type=float,
        default=10000.0,
        help="Minimum odometer standard deviation required for a usable candidate",
    )
    parser.add_argument(
        "--ready-only",
        action="store_true",
        help="Only write candidates that pass the viability gates",
    )
    parser.add_argument(
        "--only-missing-curves",
        action="store_true",
        help="Only write candidates that do not already have a live base curve",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(f"Missing input file: {args.input}")

    tagged_df, stats = load_tagged_sold_data(args.input)
    curves_df = load_curves()
    curve_tags = list_curve_tags(curves_df, include_aliases=False)
    candidate_df = build_curve_candidates(
        tagged_df,
        curve_tags=curve_tags,
        min_listings=args.min_listings,
        max_year_span=args.max_year_span,
        min_odometer_std=args.min_odometer_std,
    )

    filtered = candidate_df.copy()
    if args.ready_only:
        filtered = filtered[filtered["ready_for_curve"]].copy()
    if args.only_missing_curves:
        filtered = filtered[filtered["recommended_action"] == "build_curve"].copy()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(filtered.reindex(columns=OUTPUT_COLUMNS), args.output, index=False)

    action_counts = filtered["recommended_action"].value_counts().to_dict() if not filtered.empty else {}
    print(
        "Curve candidate queue written:",
        f"rows={len(filtered)}",
        f"classified_rows={stats['classified_rows']}",
        f"unclassified_rows={stats['unclassified_rows']}",
        f"actions={action_counts}",
        f"output={args.output}",
    )


if __name__ == "__main__":
    main()
