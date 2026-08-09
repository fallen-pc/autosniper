"""Preflight checks for paid Carsales/Apify scrape targets.

The goal is to stop spending scrape budget on broad targets that mostly
duplicate existing curve coverage. The checks are intentionally local: they use
current governed curves plus already imported Carsales staging evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.canonical_tagging import tag_dataframe
    from shared.curves import load_curves, resolve_curve_canonical_tag
    from shared.data_loader import dataset_path
else:  # pragma: no cover
    from shared.canonical_tagging import tag_dataframe
    from shared.curves import load_curves, resolve_curve_canonical_tag
    from shared.data_loader import dataset_path


DEFAULT_CARSALES_PATH = dataset_path("quality/carsales_apify_listings.csv")
DEFAULT_ACTIVE_PATH = dataset_path("active_vehicle_details.csv")
DEFAULT_MIN_NEW_LANE_ROWS = 10
DEFAULT_MAX_ALREADY_COVERED_SHARE = 0.35


@dataclass(frozen=True)
class PreflightResult:
    status: str
    target_label: str
    staging_rows: int
    already_covered_rows: int
    newly_supported_rows: int
    still_unclassified_rows: int
    already_covered_share: float
    new_or_unclassified_share: float
    buildable_uncovered_groups: int
    active_uncovered_rows: int
    recommendation: str


def _normalize_text(value: object) -> str:
    return str(value or "").strip().lower()


def _contains_or_blank(series: pd.Series, needle: str) -> pd.Series:
    needle = _normalize_text(needle)
    if not needle:
        return pd.Series(True, index=series.index)
    return series.fillna("").astype(str).str.lower().str.contains(needle, regex=False)


def _equals_or_blank(series: pd.Series, value: str) -> pd.Series:
    value = _normalize_text(value)
    if not value:
        return pd.Series(True, index=series.index)
    return series.fillna("").astype(str).str.lower().eq(value)


def filter_carsales_rows(
    df: pd.DataFrame,
    *,
    make: str = "",
    model: str = "",
    body_type: str = "",
    transmission: str = "",
    fuel_type: str = "",
    state: str = "",
    seller_type: str = "",
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    mask = pd.Series(True, index=df.index)
    for column, value in {
        "make": make,
        "model": model,
        "body_type": body_type,
        "transmission": transmission,
        "state": state,
        "seller_type": seller_type,
    }.items():
        if column in df.columns:
            mask &= _equals_or_blank(df[column], value)
    if "fuel_type" in df.columns:
        mask &= _contains_or_blank(df["fuel_type"], fuel_type)
    return df[mask].copy()


def filter_active_rows(
    df: pd.DataFrame,
    *,
    make: str = "",
    model: str = "",
    body_type: str = "",
    transmission: str = "",
    fuel_type: str = "",
    state: str = "",
    seller_type: str = "",
) -> pd.DataFrame:
    del seller_type
    if df.empty:
        return df.copy()
    mask = pd.Series(True, index=df.index)
    for column, value in {
        "make": make,
        "model": model,
        "body_type": body_type,
        "transmission": transmission,
    }.items():
        if column in df.columns:
            mask &= _equals_or_blank(df[column], value)
    if "fuel_type" in df.columns:
        mask &= _contains_or_blank(df["fuel_type"], fuel_type)
    if state and "location" in df.columns:
        mask &= _contains_or_blank(df["location"], state)
    return df[mask].copy()


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _group_columns(df: pd.DataFrame) -> list[str]:
    return [
        column
        for column in ["make", "model", "series", "badge", "body_type", "transmission", "fuel_type"]
        if column in df.columns
    ]


def _count_buildable_uncovered_groups(tagged: pd.DataFrame, *, min_rows: int) -> int:
    if tagged.empty:
        return 0
    unclassified = tagged[tagged["coverage_bucket"].eq("still_unclassified")].copy()
    if unclassified.empty:
        return 0
    group_cols = _group_columns(unclassified)
    if not group_cols:
        return 0
    counts = unclassified.groupby(group_cols, dropna=False).size()
    return int((counts >= min_rows).sum())


def _apply_coverage_buckets(df: pd.DataFrame, saved_curve_tags: set[str]) -> pd.DataFrame:
    if df.empty:
        out = df.copy()
        out["canonical_tag"] = []
        out["canonical_reason"] = []
        out["base_curve_tag"] = []
        out["coverage_bucket"] = []
        return out
    tagged = tag_dataframe(df, source="carsales_scrape_preflight", require_price=True, append_log=False)
    tagged["base_curve_tag"] = tagged["canonical_tag"].apply(resolve_curve_canonical_tag)
    tagged["coverage_bucket"] = "still_unclassified"
    classified = tagged["canonical_tag"].ne("UNCLASSIFIED")
    tagged.loc[classified & tagged["base_curve_tag"].isin(saved_curve_tags), "coverage_bucket"] = (
        "already_covered"
    )
    tagged.loc[classified & ~tagged["base_curve_tag"].isin(saved_curve_tags), "coverage_bucket"] = (
        "newly_supported"
    )
    return tagged


def summarize_target_groups(tagged: pd.DataFrame, *, limit: int = 12) -> pd.DataFrame:
    if tagged.empty:
        return pd.DataFrame()
    group_cols = _group_columns(tagged) + ["coverage_bucket"]
    summary = (
        tagged.groupby(group_cols, dropna=False)
        .size()
        .reset_index(name="rows")
        .sort_values("rows", ascending=False)
        .head(limit)
    )
    return summary


def run_preflight(
    *,
    make: str = "",
    model: str = "",
    body_type: str = "",
    transmission: str = "",
    fuel_type: str = "",
    state: str = "",
    seller_type: str = "private",
    carsales_path: Path = DEFAULT_CARSALES_PATH,
    active_path: Path = DEFAULT_ACTIVE_PATH,
    min_new_lane_rows: int = DEFAULT_MIN_NEW_LANE_ROWS,
    max_already_covered_share: float = DEFAULT_MAX_ALREADY_COVERED_SHARE,
) -> tuple[PreflightResult, pd.DataFrame]:
    curves = load_curves()
    saved_curve_tags = {
        str(tag).strip()
        for tag in curves.get("canonical_tag", pd.Series(dtype="object")).dropna().astype(str).tolist()
        if str(tag).strip()
    }
    staging = filter_carsales_rows(
        _load_csv(carsales_path),
        make=make,
        model=model,
        body_type=body_type,
        transmission=transmission,
        fuel_type=fuel_type,
        state=state,
        seller_type=seller_type,
    )
    tagged = _apply_coverage_buckets(staging, saved_curve_tags)
    counts = tagged["coverage_bucket"].value_counts() if not tagged.empty else pd.Series(dtype="int64")
    staging_rows = int(len(tagged))
    already = int(counts.get("already_covered", 0))
    new = int(counts.get("newly_supported", 0))
    unclassified = int(counts.get("still_unclassified", 0))
    already_share = already / staging_rows if staging_rows else 0.0
    useful_share = (new + unclassified) / staging_rows if staging_rows else 0.0
    buildable_groups = _count_buildable_uncovered_groups(tagged, min_rows=min_new_lane_rows)

    active = filter_active_rows(
        _load_csv(active_path),
        make=make,
        model=model,
        body_type=body_type,
        transmission=transmission,
        fuel_type=fuel_type,
        state=state,
        seller_type=seller_type,
    )
    active_tagged = _apply_coverage_buckets(active, saved_curve_tags)
    active_uncovered = int((active_tagged.get("coverage_bucket", pd.Series(dtype="object")) != "already_covered").sum())

    status = "pass"
    recommendation = "Proceed only if this target is an intentional missing-lane scrape."
    if staging_rows and already_share > max_already_covered_share and buildable_groups == 0 and active_uncovered == 0:
        status = "block"
        recommendation = "Blocked: local evidence suggests this target mostly duplicates existing curves."
    elif staging_rows and already_share > max_already_covered_share:
        status = "warn"
        recommendation = "High duplicate share; narrow the target before spending or mark it as an intentional refresh."
    elif not staging_rows and active_uncovered == 0:
        status = "warn"
        recommendation = "No local staging rows and no active uncovered rows matched; verify the target manually before spending."

    target_parts = [part for part in [make, model, body_type, transmission, fuel_type, state] if part]
    target_label = " / ".join(target_parts) or "<broad>"
    result = PreflightResult(
        status=status,
        target_label=target_label,
        staging_rows=staging_rows,
        already_covered_rows=already,
        newly_supported_rows=new,
        still_unclassified_rows=unclassified,
        already_covered_share=round(already_share, 4),
        new_or_unclassified_share=round(useful_share, 4),
        buildable_uncovered_groups=buildable_groups,
        active_uncovered_rows=active_uncovered,
        recommendation=recommendation,
    )
    return result, summarize_target_groups(tagged)


def _format_summary(summary: pd.DataFrame) -> str:
    if summary.empty:
        return ""
    return summary.to_string(index=False)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--body-type", default="")
    parser.add_argument("--transmission", default="")
    parser.add_argument("--fuel-type", default="")
    parser.add_argument("--state", default="")
    parser.add_argument("--seller-type", default="private")
    parser.add_argument("--carsales-path", type=Path, default=DEFAULT_CARSALES_PATH)
    parser.add_argument("--active-path", type=Path, default=DEFAULT_ACTIVE_PATH)
    parser.add_argument("--min-new-lane-rows", type=int, default=DEFAULT_MIN_NEW_LANE_ROWS)
    parser.add_argument("--max-already-covered-share", type=float, default=DEFAULT_MAX_ALREADY_COVERED_SHARE)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    result, summary = run_preflight(
        make=args.make,
        model=args.model,
        body_type=args.body_type,
        transmission=args.transmission,
        fuel_type=args.fuel_type,
        state=args.state,
        seller_type=args.seller_type,
        carsales_path=args.carsales_path,
        active_path=args.active_path,
        min_new_lane_rows=args.min_new_lane_rows,
        max_already_covered_share=args.max_already_covered_share,
    )
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
        if not summary.empty:
            print(json.dumps({"top_groups": summary.to_dict(orient="records")}, indent=2, sort_keys=True))
    else:
        print(f"preflight_status={result.status}")
        for key, value in asdict(result).items():
            if key != "status":
                print(f"{key}={value}")
        formatted = _format_summary(summary)
        if formatted:
            print("top_local_groups:")
            print(formatted)
    return 0 if result.status != "block" else 2


if __name__ == "__main__":
    raise SystemExit(main())
