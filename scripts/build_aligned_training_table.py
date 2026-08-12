"""Build the aligned sold-car training table that mirrors pages/6_AI_ANALYSIS.py.

This script separates the *training row source* from the *baseline source*:

  - Training rows: sold_cars.csv (all states, ~18k rows) for maximum volume.
    Already has canonical_tag; no group-map join needed.
  - Baseline: sold_cars_restricted.csv groupby(curve_tag).median(price_numeric)
    — exactly what the live AI analysis page computes at inference time.

This means the model trains on ratios that will be consistent with what it sees
at inference time, while having enough data to generalise.

Pipeline:
  1. Load baseline source (sold_cars_restricted.csv), compute groupby-median stats
  2. Load training source (sold_cars.csv), resolve canonical_tag -> curve_tag
  3. Filter training rows: curve_tag in curves.csv, no Corolla sport, no engine defects
  4. Join baseline stats onto training rows by curve_tag (+ year_int fallback)
  5. Run repair enrichment inline
  6. Add temporal + repair-tag features
  7. Merge snapshot features (optional)
  8. Write output CSV

Usage:
    python -m scripts.build_aligned_training_table
    python -m scripts.build_aligned_training_table --output artifacts/rebuild_aligned/sold_training_table.csv
    python -m scripts.build_aligned_training_table --training-source CSV_data/sold_cars.csv
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.comps_engine import parse_currency, parse_numeric
from shared.curves import list_curve_tags, load_curves, resolve_curve_canonical_tag
from shared.data_loader import dataset_path
from shared.repair_features import REPAIR_CATEGORIES, build_repair_features

# ---- same patterns as 6_AI_ANALYSIS.py ----
SPORT_TRIM_PATTERN = re.compile(r"\b(sport|sports|sx|zr|zrx)\b|sportivo|levin", re.IGNORECASE)
ENGINE_DEFECT_PATTERN = re.compile(r"engine noise observed|engine idling rough", re.IGNORECASE)

DEFAULT_TRAINING_SOURCE = dataset_path("sold_cars.csv")          # all-states, for training volume
DEFAULT_BASELINE_SOURCE = dataset_path("sold_cars_restricted.csv")  # VIC-focused, matches live page
DEFAULT_GROUP_MAP = dataset_path("restricted_group_map.csv")
DEFAULT_SNAPSHOTS = dataset_path("active_snapshots.csv")
DEFAULT_SNAPSHOT_ARCHIVE_DIR = dataset_path("archives/active_snapshots")
DEFAULT_OUTPUT = ROOT_DIR / "artifacts" / "rebuild_aligned" / "sold_training_table.csv"


# ---------------------------------------------------------------------------
# Filters (copied from 6_AI_ANALYSIS.py to stay in sync)
# ---------------------------------------------------------------------------


def _exclude_corolla_sport_comps(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "canonical_tag" not in df.columns:
        return df
    corolla_mask = df["canonical_tag"].astype(str).str.lower().str.startswith("toyota_corolla")
    if not corolla_mask.any():
        return df
    text_fields = [f for f in ("variant", "model", "series", "trim") if f in df.columns]
    if not text_fields:
        return df
    text_series = (
        df.loc[corolla_mask, text_fields]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .str.lower()
    )
    sport_mask = text_series.str.contains(SPORT_TRIM_PATTERN, na=False)
    if not sport_mask.any():
        return df
    return df.drop(index=text_series[sport_mask].index)


def _exclude_major_engine_defects(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "general_condition" not in df.columns:
        return df

    def _has_major(text: object) -> bool:
        if text is None or (isinstance(text, float) and pd.isna(text)):
            return False
        if ENGINE_DEFECT_PATTERN.search(str(text)):
            return True
        features = build_repair_features(text)
        return "engine_mechanical" in features.tags or "non_operational" in features.tags

    mask = df["general_condition"].apply(_has_major)
    return df.loc[~mask].copy()


# ---------------------------------------------------------------------------
# Repair feature extraction
# ---------------------------------------------------------------------------


def _run_repair_enrichment(df: pd.DataFrame) -> pd.DataFrame:
    """Apply repair feature extraction inline using build_repair_features."""
    from shared.repair_features import build_repair_features, serialize_tags
    from shared.repair_pricing import assess_repairs, vehicle_class_for_listing

    feature_rows = []
    cost_rows = []
    for _, row in df.iterrows():
        text = str(row.get("general_condition") or "")
        feats = build_repair_features(text)
        feature_rows.append({
            "general_condition_norm": feats.normalized_text,
            "condition_clean": feats.clean_text,
            "defects_only": feats.defects_only,
            "repair_tags": serialize_tags(feats.tags),
            "repair_severity": feats.severity,
            "decision_condition_only": feats.decision_label,
        })
        assessment = assess_repairs(text, vehicle_class=vehicle_class_for_listing(row))
        cost_rows.append({
            "estimated_parts_cost_aud": assessment.total_cost,
            "parts_cost_basis": assessment.severity_level,
        })

    enriched = pd.DataFrame(feature_rows, index=df.index)
    costs = pd.DataFrame(cost_rows, index=df.index)
    # Drop any columns we're about to add to avoid duplicates
    add_cols = list(enriched.columns) + list(costs.columns)
    df = df.drop(columns=[c for c in add_cols if c in df.columns], errors="ignore")
    return pd.concat([df, enriched, costs], axis=1)


# ---------------------------------------------------------------------------
# Repair tag one-hot features
# ---------------------------------------------------------------------------


def _add_repair_tag_features(df: pd.DataFrame) -> pd.DataFrame:
    if "repair_tags" not in df.columns:
        return df

    def _parse_tags(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(t).strip() for t in value if t]
        if isinstance(value, str):
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, list):
                    return [str(t).strip() for t in parsed if t]
            except (ValueError, SyntaxError):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return [str(t).strip() for t in parsed if t]
                except json.JSONDecodeError:
                    pass
            return [p.strip() for p in value.strip("[]").split(",") if p.strip()]
        return []

    parsed = df["repair_tags"].apply(_parse_tags)
    for tag in REPAIR_CATEGORIES:
        df[f"tag_{tag}"] = parsed.apply(lambda tags, t=tag: 1 if t in tags else 0)
    df["total_repair_tags"] = parsed.apply(len)
    return df


# ---------------------------------------------------------------------------
# Temporal features
# ---------------------------------------------------------------------------


def _add_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    date_col = next((c for c in ("date_sold", "sold_date", "auction_end") if c in df.columns), None)
    if date_col is None:
        return df
    dates = pd.to_datetime(df[date_col], errors="coerce")
    df["date_sold_parsed"] = dates
    if "year" in df.columns:
        df["vehicle_year_numeric"] = pd.to_numeric(df["year"], errors="coerce")
        df["vehicle_age_years"] = dates.dt.year - df["vehicle_year_numeric"]
        df["vehicle_age_years"] = df["vehicle_age_years"].replace(0, pd.NA)
    if "odometer_numeric" in df.columns and "vehicle_age_years" in df.columns:
        denom = df["vehicle_age_years"].replace({0: pd.NA})
        df["odometer_per_year"] = df["odometer_numeric"] / denom
    return df


# ---------------------------------------------------------------------------
# Snapshot merge (optional; same logic as prepare_sold_training_data.py)
# ---------------------------------------------------------------------------


def _load_snapshot_rows(snapshot_path: Path, archive_dir: Path | None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if snapshot_path.exists():
        cur = pd.read_csv(snapshot_path, low_memory=False)
        if not cur.empty:
            frames.append(cur)
    if archive_dir is not None and archive_dir.exists():
        for p in sorted(archive_dir.glob("active_snapshots_*.csv")):
            arc = pd.read_csv(p, low_memory=False)
            if not arc.empty:
                frames.append(arc)
    if not frames:
        return pd.DataFrame()
    snap = pd.concat(frames, ignore_index=True, sort=False)
    if "snapshot_ts" in snap.columns:
        snap["snapshot_ts"] = pd.to_datetime(snap["snapshot_ts"], errors="coerce", utc=True).dt.tz_convert(None)
    return snap


def _merge_snapshot_features(df: pd.DataFrame, snapshot_path: Path, archive_dir: Path | None) -> pd.DataFrame:
    snap = _load_snapshot_rows(snapshot_path, archive_dir)
    if snap.empty or "url" not in snap.columns or "snapshot_ts" not in snap.columns:
        return df
    snap = snap.sort_values("snapshot_ts").drop_duplicates(subset=["url"], keep="last")
    rename_map = {
        "price_numeric": "snapshot_price_numeric",
        "bids_numeric": "snapshot_bids_numeric",
        "time_remaining_hours": "snapshot_time_remaining_hours",
        "status": "snapshot_status",
        "location_state": "snapshot_location_state",
    }
    snap = snap.rename(columns=rename_map)
    merged = df.merge(snap, on="url", how="left")
    if "date_sold_parsed" in merged.columns and "snapshot_ts" in merged.columns:
        merged["snapshot_hours_to_close"] = (
            merged["date_sold_parsed"] - merged["snapshot_ts"]
        ).dt.total_seconds() / 3600.0
    return merged


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build aligned sold training table matching live AI analysis page.")
    p.add_argument("--training-source", type=Path, default=DEFAULT_TRAINING_SOURCE,
                   help="Sold CSV used for training rows (default: sold_cars.csv, all states).")
    p.add_argument("--baseline-source", type=Path, default=DEFAULT_BASELINE_SOURCE,
                   help="Sold CSV used to compute groupby-median baseline (default: sold_cars_restricted.csv).")
    p.add_argument("--group-map", type=Path, default=DEFAULT_GROUP_MAP,
                   help="Path to restricted_group_map.csv (used to add canonical_tag to baseline source).")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                   help="Output CSV path.")
    p.add_argument("--snapshots-path", type=Path, default=DEFAULT_SNAPSHOTS,
                   help="Active snapshot log path.")
    p.add_argument("--snapshot-archive-dir", type=Path, default=DEFAULT_SNAPSHOT_ARCHIVE_DIR,
                   help="Archived active snapshot directory.")
    p.add_argument("--skip-repair-enrichment", action="store_true",
                   help="Skip repair enrichment (faster iteration).")
    p.add_argument("--min-comps-count", type=int, default=3,
                   help="Min samples in baseline source per curve_tag to include a training row (default 3).")
    p.add_argument("--train-cutoff-date", type=str, default=None,
                   help="Baseline stats cutoff date (format YYYY-MM-DD). Rows sold after this are excluded from baseline to prevent self-inclusion.")
    return p.parse_args()


def _load_baseline_stats(baseline_path: Path, group_map_path: Path, train_cutoff_date: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute groupby-median stats from the restricted source (mirrors live page).

    Returns (stats_group, stats_year) indexed by curve_tag and (curve_tag, year_int).
    The restricted CSV has no canonical_tag, so we join the group map first.

    If train_cutoff_date is provided (format 'YYYY-MM-DD'), only rows sold on or before
    that date are used to compute baseline stats. This prevents evaluation rows from
    inflating the baseline medians (self-inclusion leak).
    """
    print(f"Loading baseline source: {baseline_path}")
    bdf = pd.read_csv(baseline_path, low_memory=False)
    bdf["url"] = bdf["url"].astype(str).str.strip()
    bdf["price_numeric"] = bdf["price"].apply(parse_currency) if "price" in bdf.columns else pd.NA

    # Restricted CSV has no canonical_tag — join group map
    if "canonical_tag" not in bdf.columns:
        if not group_map_path.exists():
            print(f"  ERROR: baseline source has no canonical_tag and group map not found: {group_map_path}")
            return pd.DataFrame(), pd.DataFrame()
        gm = pd.read_csv(group_map_path)
        sold_gm = gm[gm["source"] == "sold"][["url", "canonical_tag"]].copy()
        bdf = bdf.merge(sold_gm, on="url", how="inner")
        print(f"  After joining group map: {len(bdf):,} rows with canonical_tag")

    bdf["curve_tag"] = bdf["canonical_tag"].astype(str).str.strip().apply(resolve_curve_canonical_tag)
    bdf["year_int"] = pd.to_numeric(bdf.get("year", pd.Series(dtype=float, index=bdf.index)), errors="coerce").astype("Int64")

    valid = bdf.dropna(subset=["curve_tag", "price_numeric"])
    valid = valid[valid["price_numeric"] > 0]

    # Filter to train-only period if cutoff provided (prevents self-inclusion)
    if train_cutoff_date is not None:
        date_col = next((c for c in ("date_sold", "sold_date", "auction_end") if c in valid.columns), None)
        if date_col:
            valid["_date_parsed"] = pd.to_datetime(valid[date_col], errors="coerce")
            before_cutoff = valid["_date_parsed"] <= train_cutoff_date
            print(f"  Filtering to train-only period (<= {train_cutoff_date}): {before_cutoff.sum():,} of {len(valid):,} rows")
            valid = valid[before_cutoff].copy()
            valid = valid.drop(columns=["_date_parsed"])

    stats_group = (
        valid.groupby("curve_tag")["price_numeric"]
        .agg(["count", "median"])
        .rename(columns={"count": "comps_count_group", "median": "comps_median"})
    )
    stats_year = (
        valid.dropna(subset=["year_int"])
        .groupby(["curve_tag", "year_int"])["price_numeric"]
        .agg(["count", "median"])
        .rename(columns={"count": "comps_count_year", "median": "comps_median_year"})
    )
    print(f"  Baseline stats: {stats_group.index.nunique()} curve_tags")
    return stats_group, stats_year


def main() -> None:
    args = parse_args()

    # ------------------------------------------------------------------
    # 1. Compute baseline stats from restricted source (live-page baseline)
    # ------------------------------------------------------------------
    if not args.baseline_source.exists():
        print(f"ERROR: baseline source not found: {args.baseline_source}")
        sys.exit(1)
    stats_group, stats_year = _load_baseline_stats(args.baseline_source, args.group_map, train_cutoff_date=args.train_cutoff_date)

    # ------------------------------------------------------------------
    # 2. Load training rows
    # ------------------------------------------------------------------
    if not args.training_source.exists():
        print(f"ERROR: training source not found: {args.training_source}")
        sys.exit(1)
    print(f"Loading training rows from: {args.training_source}")
    df = pd.read_csv(args.training_source, low_memory=False)

    dupes = df.columns[df.columns.duplicated()].tolist()
    if dupes:
        print(f"  Warning: dropping {len(dupes)} duplicate column(s): {dupes}")
        df = df.loc[:, ~df.columns.duplicated(keep="first")]

    print(f"  Loaded {len(df):,} rows, {len(df.columns)} columns")

    df["url"] = df["url"].astype(str).str.strip()
    df["odometer_numeric"] = df["odometer_reading"].apply(parse_numeric) if "odometer_reading" in df.columns else pd.NA
    df["price_numeric"] = df["price"].apply(parse_currency) if "price" in df.columns else pd.NA
    df["bids_numeric"] = df["bids"].apply(parse_numeric) if "bids" in df.columns else 0.0

    # ------------------------------------------------------------------
    # 3. Add canonical_tag if missing (restricted CSV needs group map join)
    # ------------------------------------------------------------------
    if "canonical_tag" not in df.columns:
        if not args.group_map.exists():
            print(f"ERROR: training source has no canonical_tag and group map not found: {args.group_map}")
            sys.exit(1)
        gm = pd.read_csv(args.group_map)
        sold_gm = gm[gm["source"] == "sold"][["url", "canonical_tag"]].copy()
        df = df.merge(sold_gm, on="url", how="inner")
        print(f"  After joining group map: {len(df):,} rows with canonical_tag")

    curves_df = load_curves()
    allowed_tags = set(list_curve_tags(curves_df))
    df["curve_tag"] = df["canonical_tag"].astype(str).str.strip().apply(resolve_curve_canonical_tag)
    before = len(df)
    df = df[df["curve_tag"].isin(allowed_tags)].copy()
    print(f"  After curve_tag filter (must be in curves.csv): {before:,} -> {len(df):,} rows")

    # ------------------------------------------------------------------
    # 4. Corolla sport filter
    # ------------------------------------------------------------------
    before = len(df)
    df = _exclude_corolla_sport_comps(df)
    print(f"  After Corolla sport exclusion: {before:,} -> {len(df):,} rows")

    # ------------------------------------------------------------------
    # 5. Engine defect filter
    # ------------------------------------------------------------------
    before = len(df)
    df = _exclude_major_engine_defects(df)
    print(f"  After engine defect exclusion: {before:,} -> {len(df):,} rows")

    # ------------------------------------------------------------------
    # 6. Join baseline stats from restricted source
    # ------------------------------------------------------------------
    df["year_int"] = pd.to_numeric(df.get("year", pd.Series(dtype=float, index=df.index)), errors="coerce").astype("Int64")

    if not stats_group.empty:
        df = df.join(stats_group, on="curve_tag", how="left")
    else:
        df["comps_count_group"] = 0
        df["comps_median"] = pd.NA

    if not stats_year.empty and "year_int" in df.columns:
        df = df.join(stats_year, on=["curve_tag", "year_int"], how="left")
        use_year = df["comps_count_year"].fillna(0) >= 3
        df["comps_p50"] = df["comps_median_year"].where(use_year, df["comps_median"])
    else:
        df["comps_p50"] = df["comps_median"]

    # Drop rows with no baseline (curve_tag not in restricted source at all)
    before = len(df)
    df = df[df["comps_p50"].notna() & (df["comps_p50"] > 0)].copy()
    print(f"  After requiring valid comps_p50 (must have baseline in restricted source): {before:,} -> {len(df):,} rows")

    # Drop groups where baseline source has too few samples
    if args.min_comps_count > 0:
        before = len(df)
        df = df[df["comps_count_group"].fillna(0) >= args.min_comps_count].copy()
        print(f"  After min_comps_count >= {args.min_comps_count} in baseline source: {before:,} -> {len(df):,} rows")

    print(f"  Unique curve_tags in training set: {df['curve_tag'].nunique()}")

    # ------------------------------------------------------------------
    # 7. Repair enrichment
    # ------------------------------------------------------------------
    if args.skip_repair_enrichment:
        print("  Skipping repair enrichment (--skip-repair-enrichment set).")
    elif "general_condition" in df.columns:
        print("  Running repair enrichment...")
        df = _run_repair_enrichment(df)
        print("  Repair enrichment done.")
    else:
        print("  No 'general_condition' column found, skipping repair enrichment.")

    # ------------------------------------------------------------------
    # 8. Repair tag one-hot features
    # ------------------------------------------------------------------
    df = _add_repair_tag_features(df)

    # ------------------------------------------------------------------
    # 9. Temporal features
    # ------------------------------------------------------------------
    df = _add_temporal_features(df)

    # ------------------------------------------------------------------
    # 10. Snapshot features (optional)
    # ------------------------------------------------------------------
    if args.snapshots_path.exists():
        print("  Merging snapshot features...")
        df = _merge_snapshot_features(df, args.snapshots_path, args.snapshot_archive_dir)

    # ------------------------------------------------------------------
    # 11. Write output
    # ------------------------------------------------------------------
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(df, args.output, index=False)
    print(f"\nTraining table written to {args.output} ({len(df):,} rows)")
    print(f"  Training source: {args.training_source}")
    print(f"  Baseline source: {args.baseline_source} (groupby-year median where count>=3, else groupby median)")
    print(f"  Columns: {len(df.columns)}")

    # Ratio distribution sanity check
    valid = df[df["price_numeric"].notna() & df["comps_p50"].notna() & (df["comps_p50"] > 0)].copy()
    valid["_ratio"] = valid["price_numeric"] / valid["comps_p50"]
    p10 = float(valid["_ratio"].quantile(0.10))
    p50 = float(valid["_ratio"].quantile(0.50))
    p90 = float(valid["_ratio"].quantile(0.90))
    print(f"  Ratio (price/baseline): p10={p10:.3f}  p50={p50:.3f}  p90={p90:.3f}")
    if abs(p50 - 1.0) > 0.20:
        print(f"  WARNING: median ratio {p50:.3f} is far from 1.0 -- check price/baseline alignment")
    else:
        print("  Ratio healthy (median near 1.0)")


if __name__ == "__main__":
    main()
