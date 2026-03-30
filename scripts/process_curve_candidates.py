"""Process ranked curve candidates with AI and enqueue Autotrader scrapes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import find_dotenv, load_dotenv
from openai import OpenAI

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from scripts.curve_validator import build_curve_warnings
    from scripts.generate_curve_candidates import load_tagged_sold_data
    from shared.canonical_tagging import tag_dataframe
    from shared.curves import CURVE_COLUMNS, load_curves, resolve_curve_canonical_tag, save_curves
    from shared.data_loader import dataset_path
else:  # pragma: no cover
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from scripts.curve_validator import build_curve_warnings
    from scripts.generate_curve_candidates import load_tagged_sold_data
    from shared.canonical_tagging import tag_dataframe
    from shared.curves import CURVE_COLUMNS, load_curves, resolve_curve_canonical_tag, save_curves
    from shared.data_loader import dataset_path


DEFAULT_QUEUE_PATH = dataset_path("quality/curve_candidates.csv")
DEFAULT_BUILD_LOG_PATH = dataset_path("quality/curve_build_log.csv")
DEFAULT_AUTOTRADER_QUEUE_PATH = dataset_path("quality/autotrader_scrape_queue.csv")
DEFAULT_AUTOTRADER_SOURCE = Path("autotrader_isolated/output/autotrader_recent_market_tagged.csv")
LEGACY_AUTOTRADER_SOURCE = Path("autotrader_isolated/output/first_page_results_tagged.csv")
DEFAULT_AUTOTRADER_STATE = Path("autotrader_isolated/output/listing_state.csv")
DEFAULT_AUTOTRADER_URLS_PATH = Path("autotrader_isolated/output/curve_seed_urls.txt")
DEFAULT_AUTOTRADER_OUTPUT = Path("autotrader_isolated/output/first_page_results_tagged.csv")
DEFAULT_SOLD_PATH = dataset_path("sold_cars.csv")
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
BUILD_LOG_COLUMNS = [
    "timestamp",
    "curve_tag",
    "recommended_action",
    "result_status",
    "model",
    "confidence",
    "anchor_years",
    "autotrader_seed_url",
    "warning_count",
    "max_mid_shift_pct",
    "notes",
]
CURVE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "canonical_tag": {"type": "string"},
                    "anchor_year": {"type": "integer"},
                    "km_bucket": {"type": "integer"},
                    "price_low": {"type": "integer"},
                    "price_mid": {"type": "integer"},
                    "price_high": {"type": "integer"},
                },
                "required": [
                    "canonical_tag",
                    "anchor_year",
                    "km_bucket",
                    "price_low",
                    "price_mid",
                    "price_high",
                ],
            },
        },
    },
    "required": ["confidence", "notes", "rows"],
}

_client: OpenAI | None = None
_dotenv_loaded = False


def _ensure_api_key(env_local: Path) -> None:
    if os.getenv("OPENAI_API_KEY"):
        return
    if env_local.exists():
        for line in env_local.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                _, value = line.split("=", 1)
                os.environ["OPENAI_API_KEY"] = value.strip()
                return


def _get_client() -> OpenAI:
    global _client
    global _dotenv_loaded
    if not _dotenv_loaded:
        dotenv_files: list[Path] = []
        env_local = Path(".env.local")
        if env_local.exists():
            dotenv_files.append(env_local)
        found_env = find_dotenv()
        if found_env:
            dotenv_files.append(Path(found_env))
        if not dotenv_files:
            load_dotenv()
        else:
            for file_path in dotenv_files:
                load_dotenv(dotenv_path=file_path, override=False)
        _ensure_api_key(env_local)
        _dotenv_loaded = True
    if _client is None:
        _client = OpenAI()
    return _client


def _slug_component(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("_", "-").replace(" ", "-")
    return "-".join(part for part in text.split("-") if part)


def _autotrader_body_slug(value: object) -> str:
    slug = _slug_component(value)
    body_map = {
        "hatch": "hatchback",
        "dualcab-ute": "ute",
        "cab-chassis": "cab-chassis",
    }
    return body_map.get(slug, slug)


def _autotrader_transmission_slug(value: object) -> str:
    slug = _slug_component(value)
    trans_map = {
        "auto": "automatic",
        "manual": "manual",
    }
    return trans_map.get(slug, slug)


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
    body = _autotrader_body_slug(parts.get("body_type"))
    transmission = _autotrader_transmission_slug(parts.get("transmission"))
    state_slug = _slug_component(state)
    city_slug = _slug_component(city)
    path_parts = ["for-sale", "used"]
    if make:
        path_parts.append(make)
    if model:
        path_parts.append(model)
    if body:
        path_parts.append(body)
    if transmission:
        path_parts.append(transmission)
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


def summarize_market_by_year(df: pd.DataFrame, *, label: str) -> list[dict[str, Any]]:
    if df.empty:
        return []
    working = df.dropna(subset=["year_numeric", "price_numeric", "odometer_numeric"]).copy()
    if working.empty:
        return []
    rows: list[dict[str, Any]] = []
    for year_value, group in working.groupby("year_numeric", sort=True):
        price_series = group["price_numeric"]
        odometer_series = group["odometer_numeric"]
        rows.append(
            {
                "source": label,
                "year": int(year_value),
                "count": int(len(group)),
                "price_min": int(round(price_series.min())),
                "price_q25": int(round(price_series.quantile(0.25))),
                "price_median": int(round(price_series.median())),
                "price_q75": int(round(price_series.quantile(0.75))),
                "price_max": int(round(price_series.max())),
                "km_median": int(round(odometer_series.median())),
            }
        )
    return rows


def market_records(df: pd.DataFrame, *, max_rows: int, variant_column: str = "variant") -> list[dict[str, Any]]:
    if df.empty:
        return []
    working = df.dropna(subset=["year_numeric", "price_numeric", "odometer_numeric"]).copy()
    if working.empty:
        return []
    working = working.sort_values(["year_numeric", "odometer_numeric", "price_numeric"])
    if len(working) > max_rows:
        step = max(1, len(working) // max_rows)
        working = working.iloc[::step].head(max_rows).copy()
    rows: list[dict[str, Any]] = []
    for _, row in working.iterrows():
        rows.append(
            {
                "year": int(row["year_numeric"]),
                "variant": str(row.get(variant_column, "") or "").strip(),
                "price": int(round(float(row["price_numeric"]))),
                "odometer": int(round(float(row["odometer_numeric"]))),
            }
        )
    return rows


def build_curve_prompt(
    *,
    curve_tag: str,
    candidate_row: dict[str, Any],
    anchor_years: list[int],
    sold_summary: list[dict[str, Any]],
    sold_records: list[dict[str, Any]],
    active_summary: list[dict[str, Any]],
    existing_curve_rows: list[dict[str, Any]],
) -> str:
    payload = {
        "curve_tag": curve_tag,
        "recommended_action": candidate_row.get("recommended_action"),
        "sample_size": int(candidate_row.get("sold_count_usable") or 0),
        "year_min": candidate_row.get("year_min"),
        "year_max": candidate_row.get("year_max"),
        "anchor_years_required": anchor_years,
        "required_km_buckets": REQUIRED_KM_BUCKETS,
        "curve_policy": {
            "goal": "Build a conservative used-car price curve in AUD.",
            "requirements": [
                "Return every anchor_year x km_bucket combination exactly once.",
                "Prices must be integers.",
                "For each row: price_low <= price_mid <= price_high.",
                "For each anchor year, prices must decrease or stay flat as km increases.",
                "Use sold data as the strongest signal for price_mid.",
                "Use recent retail market data to avoid overpricing and to shape price_high conservatively.",
                "Prefer conservative pricing when evidence is thin.",
                "Do not invent a premium not supported by the evidence.",
            ],
        },
        "sold_summary_by_year": sold_summary,
        "sold_records_sample": sold_records,
        "active_summary_by_year": active_summary,
        "existing_curve_rows": existing_curve_rows,
    }
    return (
        "You are building a canonical vehicle pricing curve for AutoSniper.\n"
        "Return JSON only with this shape:\n"
        "{"
        '"confidence": number, '
        '"notes": string, '
        '"rows": ['
        '{"canonical_tag": string, "anchor_year": integer, "km_bucket": integer, '
        '"price_low": integer, "price_mid": integer, "price_high": integer}'
        "]}\n"
        "Use the provided anchor years and km buckets exactly.\n"
        "Do not wrap the JSON in markdown fences.\n"
        "Context:\n"
        f"{json.dumps(payload, ensure_ascii=True)}"
    )


def request_curve_from_openai(
    *,
    curve_tag: str,
    candidate_row: dict[str, Any],
    anchor_years: list[int],
    sold_summary: list[dict[str, Any]],
    sold_records: list[dict[str, Any]],
    active_summary: list[dict[str, Any]],
    existing_curve_rows: list[dict[str, Any]],
    model: str,
    temperature: float,
) -> dict[str, Any]:
    client = _get_client()
    prompt = build_curve_prompt(
        curve_tag=curve_tag,
        candidate_row=candidate_row,
        anchor_years=anchor_years,
        sold_summary=sold_summary,
        sold_records=sold_records,
        active_summary=active_summary,
        existing_curve_rows=existing_curve_rows,
    )
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a conservative automotive pricing analyst. "
                    "Return valid JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    raw_content = response.choices[0].message.content or "{}"
    return json.loads(raw_content)


def request_curve_from_ollama(
    *,
    curve_tag: str,
    candidate_row: dict[str, Any],
    anchor_years: list[int],
    sold_summary: list[dict[str, Any]],
    sold_records: list[dict[str, Any]],
    active_summary: list[dict[str, Any]],
    existing_curve_rows: list[dict[str, Any]],
    model: str,
    temperature: float,
    base_url: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    prompt = build_curve_prompt(
        curve_tag=curve_tag,
        candidate_row=candidate_row,
        anchor_years=anchor_years,
        sold_summary=sold_summary,
        sold_records=sold_records,
        active_summary=active_summary,
        existing_curve_rows=existing_curve_rows,
    )
    response = requests.post(
        f"{base_url.rstrip('/')}/api/chat",
        json={
            "model": model,
            "stream": False,
            "format": CURVE_RESPONSE_SCHEMA,
            "options": {"temperature": temperature},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a conservative automotive pricing analyst. "
                        "Return valid JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    message = payload.get("message") or {}
    raw_content = str(message.get("content") or "{}").strip()
    return json.loads(raw_content)


def request_curve_from_ai(
    *,
    provider: str,
    curve_tag: str,
    candidate_row: dict[str, Any],
    anchor_years: list[int],
    sold_summary: list[dict[str, Any]],
    sold_records: list[dict[str, Any]],
    active_summary: list[dict[str, Any]],
    existing_curve_rows: list[dict[str, Any]],
    model: str,
    temperature: float,
    ollama_base_url: str,
    ollama_timeout_seconds: int,
) -> dict[str, Any]:
    if provider == "ollama":
        return request_curve_from_ollama(
            curve_tag=curve_tag,
            candidate_row=candidate_row,
            anchor_years=anchor_years,
            sold_summary=sold_summary,
            sold_records=sold_records,
            active_summary=active_summary,
            existing_curve_rows=existing_curve_rows,
            model=model,
            temperature=temperature,
            base_url=ollama_base_url,
            timeout_seconds=ollama_timeout_seconds,
        )
    return request_curve_from_openai(
        curve_tag=curve_tag,
        candidate_row=candidate_row,
        anchor_years=anchor_years,
        sold_summary=sold_summary,
        sold_records=sold_records,
        active_summary=active_summary,
        existing_curve_rows=existing_curve_rows,
        model=model,
        temperature=temperature,
    )


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


def replace_curve_rows(curves_df: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    curve_tag = str(new_rows.iloc[0]["canonical_tag"]).strip()
    base = curves_df.copy()
    if not base.empty:
        base = base[base["canonical_tag"].astype(str).str.strip() != curve_tag].copy()
    return pd.concat([base, new_rows[list(CURVE_COLUMNS)]], ignore_index=True)


def upsert_autotrader_queue(
    queue_path: Path,
    *,
    curve_tag: str,
    seed_url: str,
    state: str,
    city: str,
    action: str,
    confidence: float | None,
    notes: str,
) -> None:
    existing = pd.read_csv(queue_path, low_memory=False) if queue_path.exists() else pd.DataFrame(columns=AUTOTRADER_QUEUE_COLUMNS)
    row = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp.utcnow().isoformat(),
                "curve_tag": curve_tag,
                "seed_url": seed_url,
                "state": state,
                "city": city,
                "status": "queued",
                "curve_build_action": action,
                "curve_confidence": confidence,
                "notes": notes,
                "last_run_at": "",
                "completed_at": "",
                "last_result": "",
            }
        ]
    )
    combined = pd.concat([existing, row], ignore_index=True)
    combined = combined.drop_duplicates(subset=["curve_tag", "seed_url"], keep="last")
    write_dataframe_csv_atomic(combined.reindex(columns=AUTOTRADER_QUEUE_COLUMNS), queue_path, index=False)


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


def append_build_log(log_path: Path, row: dict[str, Any]) -> None:
    existing = pd.read_csv(log_path, low_memory=False) if log_path.exists() else pd.DataFrame(columns=BUILD_LOG_COLUMNS)
    combined = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    write_dataframe_csv_atomic(combined.reindex(columns=BUILD_LOG_COLUMNS), log_path, index=False)


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
            "Process ready curve candidates with OpenAI, write validated curves.csv rows, "
            "and enqueue matching Autotrader scrapes."
        )
    )
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE_PATH, help="Path to curve_candidates.csv")
    parser.add_argument("--sold", type=Path, default=DEFAULT_SOLD_PATH, help="Path to sold_cars.csv")
    parser.add_argument(
        "--autotrader-source",
        type=Path,
        default=DEFAULT_AUTOTRADER_SOURCE,
        help="Tagged recent Autotrader market snapshot used as curve evidence",
    )
    parser.add_argument("--log-path", type=Path, default=DEFAULT_BUILD_LOG_PATH, help="Curve build log CSV")
    parser.add_argument(
        "--autotrader-queue-path",
        type=Path,
        default=DEFAULT_AUTOTRADER_QUEUE_PATH,
        help="Autotrader scrape queue CSV",
    )
    parser.add_argument("--limit", type=int, default=3, help="Maximum candidates to process")
    parser.add_argument("--tags", nargs="*", default=[], help="Optional list of curve_tag values to process")
    parser.add_argument(
        "--provider",
        default="openai",
        choices=["openai", "ollama"],
        help="AI provider for curve generation",
    )
    parser.add_argument("--model", default="gpt-4o-mini", help="Model for curve generation")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature")
    parser.add_argument(
        "--ollama-base-url",
        default="http://127.0.0.1:11434",
        help="Base URL for local Ollama API",
    )
    parser.add_argument(
        "--ollama-timeout-seconds",
        type=int,
        default=180,
        help="Timeout for Ollama chat requests",
    )
    parser.add_argument(
        "--max-mid-shift-pct",
        type=float,
        default=0.15,
        help="Reject refreshes whose max price_mid drift exceeds this fraction",
    )
    parser.add_argument("--state", default="", help="Optional Autotrader search state slug")
    parser.add_argument("--city", default="", help="Optional Autotrader search city slug")
    parser.add_argument("--dry-run", action="store_true", help="Build and validate without writing curves or queue files")
    parser.add_argument("--run-autotrader", action="store_true", help="Run the Autotrader scraper after queueing URLs")
    parser.add_argument(
        "--autotrader-urls-file",
        type=Path,
        default=DEFAULT_AUTOTRADER_URLS_PATH,
        help="Where to write queued Autotrader seed URLs",
    )
    parser.add_argument(
        "--autotrader-output",
        type=Path,
        default=DEFAULT_AUTOTRADER_OUTPUT,
        help="Autotrader scraper output CSV path when --run-autotrader is set",
    )
    parser.add_argument(
        "--storage-state",
        default="autotrader_isolated/output/storage_state.json",
        help="Playwright storage state for Autotrader scraping",
    )
    parser.add_argument(
        "--cookie-file",
        default="autotrader_isolated/output/autotrader_cookie.txt",
        help="Cookie file for Autotrader scraping",
    )
    parser.add_argument(
        "--playwright-browser",
        default="chrome",
        choices=["chromium", "chrome", "msedge", "firefox", "webkit"],
        help="Browser for Autotrader scraping",
    )
    parser.add_argument(
        "--playwright-wait",
        default="load",
        choices=["domcontentloaded", "load", "networkidle"],
        help="Playwright wait mode for Autotrader scraping",
    )
    parser.add_argument("--playwright-block-resources", action="store_true", help="Block images/fonts during Autotrader scraping")
    parser.add_argument("--playwright-headful", action="store_true", help="Show the browser during Autotrader scraping")
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

    sold_tagged_df, _stats = load_tagged_sold_data(args.sold)
    autotrader_df = load_autotrader_market(args.autotrader_source)
    curves_df = load_curves()

    processed_urls: list[str] = []
    saved_count = 0

    for _, candidate in work_df.iterrows():
        curve_tag = str(candidate.get("curve_tag", "")).strip()
        recommended_action = str(candidate.get("recommended_action", "")).strip()
        existing_rows = curves_df[curves_df["canonical_tag"].astype(str).str.strip() == curve_tag].copy()
        existing_anchor_years = (
            sorted({int(value) for value in existing_rows["anchor_year"].dropna().tolist()})
            if not existing_rows.empty and "anchor_year" in existing_rows.columns
            else []
        )

        year_min = pd.to_numeric(candidate.get("year_min"), errors="coerce")
        year_max = pd.to_numeric(candidate.get("year_max"), errors="coerce")
        anchor_years = derive_anchor_years(
            year_min=int(year_min) if pd.notna(year_min) else None,
            year_max=int(year_max) if pd.notna(year_max) else None,
            existing_anchor_years=existing_anchor_years,
        )
        if not anchor_years:
            append_build_log(
                args.log_path,
                {
                    "timestamp": pd.Timestamp.utcnow().isoformat(),
                    "curve_tag": curve_tag,
                    "recommended_action": recommended_action,
                    "result_status": "skipped",
                    "model": f"{args.provider}:{args.model}",
                    "confidence": None,
                    "anchor_years": "",
                    "autotrader_seed_url": "",
                    "warning_count": 0,
                    "max_mid_shift_pct": 0.0,
                    "notes": "Could not derive anchor years.",
                },
            )
            continue

        sold_rows = sold_tagged_df[sold_tagged_df["curve_tag"].astype(str).str.strip() == curve_tag].copy()
        active_rows = autotrader_df[autotrader_df["curve_tag"].astype(str).str.strip() == curve_tag].copy()
        sold_summary = summarize_market_by_year(sold_rows, label="sold")
        sold_records = market_records(sold_rows, max_rows=60, variant_column="variant")
        active_summary = summarize_market_by_year(active_rows, label="active")
        existing_curve_rows = (
            existing_rows.sort_values(["anchor_year", "km_bucket"])[list(CURVE_COLUMNS)].to_dict(orient="records")
            if not existing_rows.empty
            else []
        )

        seed_url = build_autotrader_seed_url(curve_tag, state=args.state, city=args.city)

        try:
            payload = request_curve_from_ai(
                provider=args.provider,
                curve_tag=curve_tag,
                candidate_row=candidate.to_dict(),
                anchor_years=anchor_years,
                sold_summary=sold_summary,
                sold_records=sold_records,
                active_summary=active_summary,
                existing_curve_rows=existing_curve_rows,
                model=args.model,
                temperature=args.temperature,
                ollama_base_url=args.ollama_base_url,
                ollama_timeout_seconds=args.ollama_timeout_seconds,
            )
            proposed_rows, errors, shift_pct = validate_curve_response(
                curve_tag=curve_tag,
                payload=payload,
                anchor_years=anchor_years,
                existing_rows=existing_rows,
                max_mid_shift_pct=args.max_mid_shift_pct,
            )
            confidence = payload.get("confidence")
            confidence_value = float(confidence) if confidence is not None else None
            notes = str(payload.get("notes", "") or "").strip()
        except Exception as exc:  # noqa: BLE001
            append_build_log(
                args.log_path,
                {
                    "timestamp": pd.Timestamp.utcnow().isoformat(),
                    "curve_tag": curve_tag,
                    "recommended_action": recommended_action,
                    "result_status": "ai_error",
                    "model": f"{args.provider}:{args.model}",
                    "confidence": None,
                    "anchor_years": "|".join(str(value) for value in anchor_years),
                    "autotrader_seed_url": seed_url,
                    "warning_count": 0,
                    "max_mid_shift_pct": 0.0,
                    "notes": str(exc),
                },
            )
            continue

        if proposed_rows is None:
            append_build_log(
                args.log_path,
                {
                    "timestamp": pd.Timestamp.utcnow().isoformat(),
                    "curve_tag": curve_tag,
                    "recommended_action": recommended_action,
                    "result_status": "validation_failed",
                    "model": f"{args.provider}:{args.model}",
                    "confidence": confidence_value,
                    "anchor_years": "|".join(str(value) for value in anchor_years),
                    "autotrader_seed_url": seed_url,
                    "warning_count": len(errors),
                    "max_mid_shift_pct": shift_pct,
                    "notes": " | ".join(errors),
                },
            )
            continue

        if not args.dry_run:
            curves_df = replace_curve_rows(curves_df, proposed_rows)
            save_curves(curves_df)
            upsert_autotrader_queue(
                args.autotrader_queue_path,
                curve_tag=curve_tag,
                seed_url=seed_url,
                state=args.state,
                city=args.city,
                action=recommended_action,
                confidence=confidence_value,
                notes=notes,
            )

        processed_urls.append(seed_url)
        saved_count += 1
        append_build_log(
            args.log_path,
            {
                "timestamp": pd.Timestamp.utcnow().isoformat(),
                "curve_tag": curve_tag,
                "recommended_action": recommended_action,
                "result_status": "saved" if not args.dry_run else "validated",
                "model": f"{args.provider}:{args.model}",
                "confidence": confidence_value,
                "anchor_years": "|".join(str(value) for value in anchor_years),
                "autotrader_seed_url": seed_url,
                "warning_count": 0,
                "max_mid_shift_pct": shift_pct,
                "notes": notes,
            },
        )

    if processed_urls:
        unique_urls = list(dict.fromkeys(processed_urls))
        args.autotrader_urls_file.parent.mkdir(parents=True, exist_ok=True)
        args.autotrader_urls_file.write_text("\n".join(unique_urls) + "\n", encoding="utf-8")
        print(f"Wrote {len(unique_urls)} Autotrader seed URL(s) to {args.autotrader_urls_file}")

        if args.run_autotrader and not args.dry_run:
            result = run_autotrader_scrape(
                urls_file=args.autotrader_urls_file,
                output_path=args.autotrader_output,
                storage_state=args.storage_state,
                cookie_file=args.cookie_file,
                browser=args.playwright_browser,
                wait_mode=args.playwright_wait,
                block_resources=args.playwright_block_resources,
                headful=args.playwright_headful,
            )
            status = "completed" if result.returncode == 0 else "failed"
            note = (result.stdout or "").strip()[-1000:]
            if result.stderr:
                stderr_note = result.stderr.strip()[-500:]
                note = f"{note}\n{stderr_note}".strip()
            update_autotrader_queue_status(
                args.autotrader_queue_path,
                seed_urls=unique_urls,
                status=status,
                result_note=note,
            )
            print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            if result.returncode != 0:
                raise SystemExit(f"Autotrader scrape failed with exit code {result.returncode}")

    print(
        "Curve processing complete:",
        f"selected={len(work_df)}",
        f"saved={saved_count}",
        f"dry_run={args.dry_run}",
    )


if __name__ == "__main__":
    main()
