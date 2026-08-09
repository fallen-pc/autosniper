"""Legacy ranked-curve processor.

Curve pricing is now intentionally centralized in Curve Builder V2, where
Carsales/manual evidence is the pricing source. This module still exposes
Autotrader queue/scrape helpers used by the operator pages, but its CLI no
longer writes curve rows.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from scripts.curve_validator import build_curve_warnings
    from shared.canonical_tagging import tag_dataframe
    from shared.curves import CURVE_COLUMNS, resolve_curve_canonical_tag
    from shared.data_loader import dataset_path
else:  # pragma: no cover
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from scripts.curve_validator import build_curve_warnings
    from shared.canonical_tagging import tag_dataframe
    from shared.curves import CURVE_COLUMNS, resolve_curve_canonical_tag
    from shared.data_loader import dataset_path


DEFAULT_QUEUE_PATH = dataset_path("quality/curve_candidates.csv")
DEFAULT_AUTOTRADER_SOURCE = Path("autotrader_isolated/output/autotrader_recent_market_tagged.csv")
LEGACY_AUTOTRADER_SOURCE = Path("autotrader_isolated/output/first_page_results_tagged.csv")
LEGACY_AI_CURVE_BUILD_DISABLED_MESSAGE = (
    "Legacy AI curve building is disabled. Use Curve Builder V2 for Carsales/manual "
    "evidence-backed curve edits; Autotrader remains comparison/scrape follow-up only."
)
REQUIRED_KM_BUCKETS = [30000, 60000, 100000, 150000, 200000]
INACTIVE_AUTOTRADER_STATUSES = {"sold", "expired", "removed"}
RECENT_MARKET_WINDOW_DAYS = 90
AUTOTRADER_QUEUE_COLUMNS = [
    "timestamp",
    "curve_tag",
    "seed_url",
    "state",
    "city",
    "status",
    "curve_build_action",
    "curve_confidence",
    "notes",
    "last_run_at",
    "completed_at",
    "last_result",
]


def _slug_component(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("_", "-").replace(" ", "-")
    return "-".join(part for part in text.split("-") if part)


def parse_curve_tag(curve_tag: str) -> dict[str, str]:
    parts = str(curve_tag or "").strip().split("_")
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


def build_autotrader_seed_url(curve_tag: str, *, state: str = "", city: str = "") -> str:
    parts = parse_curve_tag(curve_tag)
    make = _slug_component(parts.get("make"))
    model = _slug_component(parts.get("model"))
    state_slug = _slug_component(state)
    city_slug = _slug_component(city)
    path_parts = ["for-sale", "used"]
    if make:
        path_parts.append(make)
    if model:
        path_parts.append(model)
    if state_slug:
        path_parts.append(state_slug)
    if city_slug:
        path_parts.append(city_slug)
    return "https://www.autotrader.com.au/" + "/".join(path_parts)


def derive_anchor_years(
    *,
    year_min: int | None,
    year_max: int | None,
    existing_anchor_years: list[int] | None = None,
) -> list[int]:
    if existing_anchor_years:
        return sorted({int(value) for value in existing_anchor_years})
    if year_min is None or year_max is None:
        return []
    if year_min > year_max:
        year_min, year_max = year_max, year_min
    if year_min == year_max:
        return [year_min]
    span = year_max - year_min
    target_points = 3 if span <= 5 else 4
    if target_points <= 1:
        return [year_min]
    values: list[int] = []
    for index in range(target_points):
        ratio = index / float(target_points - 1)
        values.append(int(round(year_min + (span * ratio))))
    values.extend([year_min, year_max])
    return sorted({int(value) for value in values})


def _coalesce_autotrader_event_timestamp(df: pd.DataFrame) -> pd.Series:
    parsed_parts: list[pd.Series] = []
    for column in ["scrape_date", "last_seen", "last_price_date", "first_seen", "sold_date"]:
        if column not in df.columns:
            continue
        parsed_parts.append(pd.to_datetime(df[column], errors="coerce", utc=True))
    if not parsed_parts:
        return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")
    return pd.concat(parsed_parts, axis=1).max(axis=1)


def _dedupe_autotrader_active_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    working = df.copy()
    if "url" not in working.columns:
        return working

    if "scrape_date" in working.columns and working["scrape_date"].notna().any():
        working = working[working["scrape_date"].notna()].copy()
    elif "status" in working.columns:
        status_norm = working["status"].fillna("").astype(str).str.strip().str.lower()
        working = working[~status_norm.isin(INACTIVE_AUTOTRADER_STATUSES)].copy()

    if working.empty:
        return working

    # Keep the latest live listing row for each URL and drop sold-history repeats.
    working["_event_ts"] = _coalesce_autotrader_event_timestamp(working)
    working = working.sort_values(["_event_ts", "url"], ascending=[False, True], na_position="last")
    working = working.drop_duplicates(subset=["url"], keep="first")
    return working.drop(columns=["_event_ts"], errors="ignore").reset_index(drop=True)


def _build_autotrader_recent_market_from_state(
    state_path: Path,
    *,
    output_path: Path | None = None,
    recent_days: int = RECENT_MARKET_WINDOW_DAYS,
) -> pd.DataFrame:
    if not state_path.exists():
        return pd.DataFrame()
    state_df = pd.read_csv(state_path, low_memory=False)
    if state_df.empty or "url" not in state_df.columns:
        return pd.DataFrame()

    working_state = state_df.copy()
    working_state["_event_ts"] = _coalesce_autotrader_event_timestamp(working_state)
    cutoff_ts = pd.Timestamp(datetime.now(UTC) - timedelta(days=recent_days))
    recent_df = working_state[working_state["_event_ts"].notna() & (working_state["_event_ts"] >= cutoff_ts)].copy()
    if recent_df.empty:
        return pd.DataFrame()

    working = pd.DataFrame(
        {
            "year": recent_df.get("year", ""),
            "make": recent_df.get("make", ""),
            "model": recent_df.get("model", ""),
            "variant": recent_df.get("variant", ""),
            "body_type": recent_df.get("body_type", ""),
            "odometer": recent_df.get("odometer", ""),
            "transmission": recent_df.get("transmission", ""),
            "rego": recent_df.get("rego", ""),
            "price": recent_df.get("last_price", ""),
            "fuel_type": recent_df.get("fuel_type", ""),
            "location": recent_df.get("location", ""),
            "url": recent_df.get("url", ""),
            "scrape_date": recent_df["_event_ts"].astype(str),
        }
    )
    working = tag_dataframe(
        working,
        source="autotrader_recent_market_state",
        require_price=True,
        filter_unclassified=False,
        append_log=True,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        working.to_csv(output_path, index=False)
    return working


def load_carsales_apify_market(path: Path | None = None) -> pd.DataFrame:
    """Load and normalize Carsales Apify listings for curve building."""
    csv_path = path or dataset_path("quality/carsales_apify_listings.csv")
    if not csv_path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    working = df.copy()
    working = tag_dataframe(
        working,
        source="carsales_apify_market",
        require_price=True,
        append_log=False,
    )
    if "canonical_tag" not in working.columns:
        return pd.DataFrame()
    working["canonical_tag"] = working["canonical_tag"].fillna("").astype(str).str.strip()
    working["curve_tag"] = working["canonical_tag"].apply(resolve_curve_canonical_tag)
    for target, candidates in {
        "year_numeric": ["year"],
        "price_numeric": ["price"],
        "odometer_numeric": ["odometer"],
    }.items():
        resolved = pd.Series(index=working.index, dtype="float64")
        for column in candidates:
            if column not in working.columns:
                continue
            resolved = resolved.fillna(pd.to_numeric(working[column], errors="coerce"))
        working[target] = resolved
    working = working.dropna(subset=["year_numeric", "price_numeric", "odometer_numeric"]).copy()
    return working


def load_autotrader_market(path: Path) -> pd.DataFrame:
    df: pd.DataFrame
    if path.exists():
        df = pd.read_csv(path, low_memory=False)
    else:
        state_path = path.with_name("listing_state.csv")
        df = _build_autotrader_recent_market_from_state(state_path, output_path=path)
        if df.empty and path != LEGACY_AUTOTRADER_SOURCE and LEGACY_AUTOTRADER_SOURCE.exists():
            df = pd.read_csv(LEGACY_AUTOTRADER_SOURCE, low_memory=False)
    if df.empty:
        return pd.DataFrame()
    if "canonical_tag" not in df.columns:
        return pd.DataFrame()
    working = _dedupe_autotrader_active_snapshot(df)
    if working.empty:
        return working
    working["canonical_tag"] = working["canonical_tag"].fillna("").astype(str).str.strip()
    working["curve_tag"] = working["canonical_tag"].apply(resolve_curve_canonical_tag)
    for target, candidates in {
        "year_numeric": ["year_int", "year"],
        "price_numeric": ["price_value", "price", "last_price"],
        "odometer_numeric": ["odometer_value", "odometer"],
    }.items():
        resolved = pd.Series(index=working.index, dtype="float64")
        for column in candidates:
            if column not in working.columns:
                continue
            resolved = resolved.fillna(pd.to_numeric(working[column], errors="coerce"))
        working[target] = resolved
    return working


def compute_max_mid_shift_pct(existing_rows: pd.DataFrame, proposed_rows: pd.DataFrame) -> float:
    if existing_rows.empty or proposed_rows.empty:
        return 0.0
    left = existing_rows[["anchor_year", "km_bucket", "price_mid"]].rename(columns={"price_mid": "existing_mid"})
    right = proposed_rows[["anchor_year", "km_bucket", "price_mid"]].rename(columns={"price_mid": "proposed_mid"})
    merged = left.merge(right, on=["anchor_year", "km_bucket"], how="inner")
    if merged.empty:
        return 0.0
    base = pd.to_numeric(merged["existing_mid"], errors="coerce")
    proposed = pd.to_numeric(merged["proposed_mid"], errors="coerce")
    mask = base.gt(0) & proposed.notna()
    if not mask.any():
        return 0.0
    pct = ((proposed[mask] - base[mask]).abs() / base[mask]).max()
    return float(pct if pd.notna(pct) else 0.0)


def _estimate_from_points(points: list[tuple[int, int]], target: int) -> int | None:
    if len(points) < 2:
        return None
    points = sorted(points, key=lambda item: item[0])
    if target <= points[0][0]:
        (x1, y1), (x2, y2) = points[0], points[1]
    elif target >= points[-1][0]:
        (x1, y1), (x2, y2) = points[-2], points[-1]
    else:
        x1 = y1 = x2 = y2 = None
        for left, right in zip(points, points[1:]):
            if left[0] <= target <= right[0]:
                (x1, y1), (x2, y2) = left, right
                break
        if x1 is None:
            return None
    if x2 == x1:
        return int(round(y1))
    ratio = (target - x1) / float(x2 - x1)
    return int(round(y1 + ((y2 - y1) * ratio)))


def repair_curve_grid(proposed: pd.DataFrame, *, curve_tag: str, anchor_years: list[int]) -> pd.DataFrame:
    expected_pairs = {(int(year), int(km)) for year in anchor_years for km in REQUIRED_KM_BUCKETS}
    actual_pairs = set(zip(proposed["anchor_year"], proposed["km_bucket"]))
    if actual_pairs == expected_pairs:
        return proposed
    if actual_pairs - expected_pairs:
        return proposed

    missing_pairs = sorted(expected_pairs - actual_pairs)
    if len(missing_pairs) > 3:
        return proposed

    repaired = proposed.copy()
    for anchor_year, km_bucket in missing_pairs:
        row_payload: dict[str, int | str] = {
            "canonical_tag": curve_tag,
            "anchor_year": int(anchor_year),
            "km_bucket": int(km_bucket),
        }
        for column in ("price_low", "price_mid", "price_high"):
            same_year = repaired[repaired["anchor_year"] == anchor_year][["km_bucket", column]].dropna()
            estimate = _estimate_from_points(
                [(int(km), int(value)) for km, value in same_year.itertuples(index=False, name=None)],
                int(km_bucket),
            )
            if estimate is None:
                same_km = repaired[repaired["km_bucket"] == km_bucket][["anchor_year", column]].dropna()
                estimate = _estimate_from_points(
                    [(int(year), int(value)) for year, value in same_km.itertuples(index=False, name=None)],
                    int(anchor_year),
                )
            if estimate is None:
                return proposed
            row_payload[column] = int(estimate)
        repaired = pd.concat([repaired, pd.DataFrame([row_payload])], ignore_index=True)
    return repaired


def validate_curve_response(
    *,
    curve_tag: str,
    payload: dict[str, Any],
    anchor_years: list[int],
    existing_rows: pd.DataFrame,
    max_mid_shift_pct: float,
) -> tuple[pd.DataFrame | None, list[str], float]:
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return None, ["AI response missing rows."], 0.0

    proposed = pd.DataFrame(rows)
    missing_columns = [column for column in CURVE_COLUMNS if column not in proposed.columns]
    if missing_columns:
        return None, [f"AI response missing columns: {missing_columns}"], 0.0

    proposed = proposed[list(CURVE_COLUMNS)].copy()
    proposed["canonical_tag"] = proposed["canonical_tag"].fillna("").astype(str).str.strip()
    if not (proposed["canonical_tag"] == curve_tag).all():
        return None, ["AI returned rows for the wrong canonical_tag."], 0.0

    for column in ("anchor_year", "km_bucket", "price_low", "price_mid", "price_high"):
        proposed[column] = pd.to_numeric(proposed[column], errors="coerce")

    if proposed.isna().any().any():
        return None, ["AI response contains missing or non-numeric values."], 0.0

    for column in ("anchor_year", "km_bucket", "price_low", "price_mid", "price_high"):
        proposed[column] = proposed[column].round().astype(int)

    proposed = repair_curve_grid(proposed, curve_tag=curve_tag, anchor_years=anchor_years)
    expected_pairs = {(int(year), int(km)) for year in anchor_years for km in REQUIRED_KM_BUCKETS}
    actual_pairs = set(zip(proposed["anchor_year"], proposed["km_bucket"]))
    if actual_pairs != expected_pairs:
        return None, ["AI response does not contain the required anchor_year/km_bucket grid."], 0.0

    if proposed.duplicated(subset=["canonical_tag", "anchor_year", "km_bucket"]).any():
        return None, ["AI response contains duplicate rows."], 0.0

    invalid_band = proposed[
        (proposed["price_low"] <= 0)
        | (proposed["price_mid"] <= 0)
        | (proposed["price_high"] <= 0)
        | (proposed["price_low"] > proposed["price_mid"])
        | (proposed["price_mid"] > proposed["price_high"])
    ]
    if not invalid_band.empty:
        return None, ["AI response contains invalid price bands."], 0.0

    warnings_df = build_curve_warnings(proposed)
    warning_messages = warnings_df["message"].astype(str).tolist() if not warnings_df.empty else []
    if warning_messages:
        return None, warning_messages, 0.0

    year_scope = proposed.sort_values(["km_bucket", "anchor_year"])
    year_errors: list[str] = []
    for km_bucket, subset in year_scope.groupby("km_bucket", sort=True):
        mids = subset["price_mid"].tolist()
        if any(current < previous for previous, current in zip(mids, mids[1:])):
            year_errors.append(f"price_mid decreases across anchor years for km_bucket {km_bucket}.")
    if year_errors:
        return None, year_errors, 0.0

    shift_pct = compute_max_mid_shift_pct(existing_rows, proposed)
    if not existing_rows.empty and shift_pct > max_mid_shift_pct:
        return None, [f"AI curve drift too large ({shift_pct:.1%} > {max_mid_shift_pct:.1%})."], shift_pct

    return proposed.sort_values(["anchor_year", "km_bucket"]).reset_index(drop=True), [], shift_pct


def update_autotrader_queue_status(
    queue_path: Path,
    *,
    seed_urls: list[str],
    status: str,
    result_note: str = "",
) -> None:
    if not seed_urls or not queue_path.exists():
        return
    existing = pd.read_csv(queue_path, low_memory=False)
    if existing.empty or "seed_url" not in existing.columns:
        return
    for column in AUTOTRADER_QUEUE_COLUMNS:
        if column not in existing.columns:
            existing[column] = ""

    normalized_urls = {str(url).strip() for url in seed_urls if str(url).strip()}
    if not normalized_urls:
        return

    mask = existing["seed_url"].fillna("").astype(str).str.strip().isin(normalized_urls)
    if not mask.any():
        return

    timestamp = pd.Timestamp.utcnow().isoformat()
    existing.loc[mask, "status"] = status
    existing.loc[mask, "last_run_at"] = timestamp
    existing.loc[mask, "last_result"] = result_note
    if status == "completed":
        existing.loc[mask, "completed_at"] = timestamp
    write_dataframe_csv_atomic(existing.reindex(columns=AUTOTRADER_QUEUE_COLUMNS), queue_path, index=False)


def run_autotrader_scrape(
    *,
    urls_file: Path,
    output_path: Path,
    storage_state: str,
    cookie_file: str,
    browser: str,
    wait_mode: str,
    block_resources: bool,
    headful: bool,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "autotrader_isolated/scrape_first_page.py",
        "--urls-file",
        str(urls_file),
        "--output",
        str(output_path),
        "--all-pages",
        "--skip-existing",
        "--checkpoint-every",
        "100",
    ]
    if storage_state:
        command.extend(["--storage-state", storage_state])
    if cookie_file:
        command.extend(["--cookie-file", cookie_file])
    if headful:
        command.append("--playwright-headful")
    if browser:
        command.extend(["--playwright-browser", browser])
    if wait_mode:
        command.extend(["--playwright-wait", wait_mode])
    if block_resources:
        command.append("--playwright-block-resources")
    return subprocess.run(command, check=False, capture_output=True, text=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy curve-candidate CLI. Disabled by policy; use Curve Builder V2 for curve pricing."
        )
    )
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE_PATH, help="Path to curve_candidates.csv")
    parser.add_argument("--limit", type=int, default=3, help="Maximum candidates to process")
    parser.add_argument("--tags", nargs="*", default=[], help="Optional list of curve_tag values to process")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.queue.exists():
        raise SystemExit(f"Missing curve candidate queue: {args.queue}")

    queue_df = pd.read_csv(args.queue, low_memory=False)
    if queue_df.empty:
        print("Curve candidate queue is empty.")
        return

    if "curve_tag" not in queue_df.columns or "recommended_action" not in queue_df.columns:
        raise SystemExit("Queue file is missing required columns.")

    queue_df["curve_tag"] = queue_df["curve_tag"].fillna("").astype(str).str.strip()
    queue_df["recommended_action"] = queue_df["recommended_action"].fillna("").astype(str).str.strip()
    queue_df["ready_for_curve"] = queue_df.get("ready_for_curve", False).fillna(False).astype(bool)

    work_df = queue_df[queue_df["recommended_action"].isin(["build_curve", "refresh_curve"])].copy()
    if "priority_rank" in work_df.columns:
        work_df["priority_rank"] = pd.to_numeric(work_df["priority_rank"], errors="coerce")
        work_df = work_df.sort_values(["priority_rank", "curve_tag"], ascending=[True, True])
    if args.tags:
        selected_tags = {str(value).strip() for value in args.tags if str(value).strip()}
        work_df = work_df[work_df["curve_tag"].isin(selected_tags)].copy()
    if args.limit > 0:
        work_df = work_df.head(args.limit).copy()

    if work_df.empty:
        print("No buildable curve candidates selected.")
        return

    raise SystemExit(LEGACY_AI_CURVE_BUILD_DISABLED_MESSAGE)


if __name__ == "__main__":
    main()
