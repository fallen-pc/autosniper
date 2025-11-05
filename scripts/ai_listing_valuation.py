import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import os
import pandas as pd
from dotenv import load_dotenv, find_dotenv
from openai import OpenAI

from shared.data_loader import DATA_DIR


AI_RESULTS_PATH = DATA_DIR / "ai_listing_valuations.csv"
REQUIRED_COLUMNS = [
    "url",
    "analysis_timestamp",
    "carsales_price_estimate",
    "carsales_price_range",
    "recommended_max_bid",
    "expected_profit",
    "profit_margin_percent",
    "score_out_of_10",
    "confidence_notes",
    "manual_carsales_count",
    "manual_carsales_min",
    "manual_carsales_max",
    "manual_carsales_avg",
    "manual_carsales_avg_odometer",
    "manual_carsales_estimate",
    "manual_instant_offer_estimate",
    "manual_recent_sales_30d",
    "manual_carsales_table",
]

# Cost assumption for auction fees + basic reconditioning buffer (AUD).
COST_BUFFER = 1_500.0
# Max headroom we give above the current live bid before we cap the recommendation.
CURRENT_BID_HEADROOM = 3_500.0

_client: Optional[OpenAI] = None
_dotenv_loaded = False


def _ensure_api_key(env_local: Path) -> None:
    if os.getenv("OPENAI_API_KEY"):
        return
    if env_local.exists():
        for line in env_local.read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                _, value = line.split("=", 1)
                os.environ["OPENAI_API_KEY"] = value.strip()
                return


def _get_client() -> OpenAI:
    global _client
    global _dotenv_loaded
    if not _dotenv_loaded:
        # Load .env.local first (preferred), then fall back to any .env
        dotenv_files = []
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


def load_cached_results() -> pd.DataFrame:
    if not AI_RESULTS_PATH.exists():
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    try:
        df = pd.read_csv(AI_RESULTS_PATH)
    except Exception:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    for column in missing:
        df[column] = None
    return df


def _save_result_row(row: Dict[str, Any]) -> None:
    df = load_cached_results()
    new_row = pd.DataFrame([row])
    combined = pd.concat([df, new_row], ignore_index=True)
    combined = combined.drop_duplicates(subset=["url"], keep="last")
    combined.to_csv(AI_RESULTS_PATH, index=False)


def _parse_currency(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace("$", "").replace(",", "")
    numbers = re.findall(r"-?\d+(?:\.\d+)?", cleaned)
    if not numbers:
        return None
    try:
        values = [float(num) for num in numbers]
        return sum(values) / len(values) if values else None
    except ValueError:
        return None


def _format_currency(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return f"${value:,.0f}"


def _format_odometer(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    try:
        return f"{int(round(float(value))):,} km"
    except Exception:  # noqa: BLE001
        return str(value)


def _parse_int(value: Any) -> Optional[int]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(float(str(value).strip().replace(",", "")))
    except (TypeError, ValueError):
        return None


def _parse_odometer_value(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).lower().replace("km", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def update_manual_carsales_data(
    url: str,
    comparable_count: Optional[int],
    price_min: Optional[float],
    price_max: Optional[float],
    price_avg: Optional[float],
    avg_odometer: Optional[float],
    table_raw: str,
    price_estimate: Optional[str] = None,
    instant_offer_estimate: Optional[str] = None,
    recent_sales_30d: Optional[int] = None,
) -> pd.DataFrame:
    df = load_cached_results()
    if url in df["url"].values:
        idx = df.index[df["url"] == url][0]
    else:
        missing_row = {column: None for column in REQUIRED_COLUMNS}
        missing_row["url"] = url
        df = pd.concat([df, pd.DataFrame([missing_row])], ignore_index=True)
        idx = df.index[df["url"] == url][0]

    df.at[idx, "manual_carsales_count"] = (
        int(comparable_count) if comparable_count is not None else None
    )
    df.at[idx, "manual_carsales_min"] = (
        _format_currency(price_min) if price_min is not None else None
    )
    df.at[idx, "manual_carsales_max"] = (
        _format_currency(price_max) if price_max is not None else None
    )
    df.at[idx, "manual_carsales_avg"] = (
        _format_currency(price_avg) if price_avg is not None else None
    )
    df.at[idx, "manual_carsales_avg_odometer"] = (
        _format_odometer(avg_odometer) if avg_odometer is not None else None
    )
    def _clean_string(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (int, float)) and not pd.isna(value):
            return _format_currency(float(value))
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned if cleaned else None
        return None

    df.at[idx, "manual_carsales_estimate"] = _clean_string(price_estimate)
    df.at[idx, "manual_instant_offer_estimate"] = _clean_string(instant_offer_estimate)
    df.at[idx, "manual_recent_sales_30d"] = (
        int(recent_sales_30d) if recent_sales_30d is not None else None
    )
    df.at[idx, "manual_carsales_table"] = table_raw if table_raw else ""

    df.to_csv(AI_RESULTS_PATH, index=False)
    return df


def _build_prompt(listing: Dict[str, Any]) -> str:
    listing_snapshot = {
        "year": listing.get("year"),
        "make": listing.get("make"),
        "model": listing.get("model"),
        "variant": listing.get("variant"),
        "location": listing.get("location"),
        "current_bid": listing.get("current_price"),
        "hours_remaining": listing.get("hours_remaining"),
        "odometer": listing.get("odometer_reading"),
        "odometer_unit": listing.get("odometer_unit"),
        "historical_match_count": listing.get("historical_match_count"),
        "historical_median": listing.get("historical_price_median"),
        "historical_mean": listing.get("historical_price_mean"),
        "historical_min": listing.get("historical_price_min"),
        "historical_max": listing.get("historical_price_max"),
        "historical_median_discount": listing.get("median_discount"),
    }
    manual_snapshot = {
        "comparable_count": listing.get("manual_carsales_count"),
        "carsales_price_min": listing.get("manual_carsales_min"),
        "carsales_price_max": listing.get("manual_carsales_max"),
        "carsales_price_average": listing.get("manual_carsales_avg"),
        "carsales_average_odometer": listing.get("manual_carsales_avg_odometer"),
        "carsales_manual_estimate": listing.get("manual_carsales_estimate"),
        "instant_offer_estimate": listing.get("manual_instant_offer_estimate"),
        "recent_sales_30d": listing.get("manual_recent_sales_30d"),
    }
    if any(
        value not in (None, "")
        and not (isinstance(value, float) and pd.isna(value))
        for value in manual_snapshot.values()
    ):
        listing_snapshot["carsales_manual_snapshot"] = manual_snapshot
    prompt = f"""
You are an automotive pricing strategist. Evaluate the following listing and use your knowledge of Carsales.com.au market pricing for comparable vehicles in Australia. Incorporate the provided historical auction data as a wholesale reference point.

Listing snapshot (JSON):
{json.dumps(listing_snapshot, default=str)}

Instructions:
1. Estimate a realistic Carsales.com.au private sale price range (AUD) for the vehicle today.
2. Within that range, provide a single best-estimate price (AUD) you would target for resale.
3. Recommend a maximum bid (AUD) to stay profitable, assuming auction fees and reconditioning costs of $1,500 total.
4. Estimate the resulting profit (AUD) and profit margin (%) using your Carsales best-estimate resale price and recommended max bid.
5. Highlight key rationale factors or market risks in 2-3 short bullet points.
6. Provide an investment attractiveness score out of 10 (higher is better) based on resale upside versus risk.
7. If data is insufficient, be explicit and default to conservative figures.

Return only valid JSON with this exact schema:
{{
  "carsales_price_estimate": "$31000",
  "carsales_price_range": "$29500 - $32500",
  "recommended_max_bid": "$25500",
  "expected_profit": "$5500",
  "profit_margin_percent": "18%",
  "score_out_of_10": 7.5,
  "confidence_notes": [
    "short note 1",
    "short note 2"
  ]
}}

All currency values must be strings starting with "$" and rounded to the nearest $10.
The score must be numeric between 0 and 10 (inclusive) and align with your stated rationale.
"""
    return prompt


def run_ai_listing_analysis(listing_row: pd.Series, force_refresh: bool = False) -> Dict[str, Any]:
    cached_df = load_cached_results()
    url = listing_row.get("url")

    manual_count_val = _parse_int(listing_row.get("manual_carsales_count"))
    manual_min_val = _parse_currency(listing_row.get("manual_carsales_min"))
    manual_max_val = _parse_currency(listing_row.get("manual_carsales_max"))
    manual_avg_val = _parse_currency(listing_row.get("manual_carsales_avg"))
    manual_avg_odo_val = _parse_odometer_value(listing_row.get("manual_carsales_avg_odometer"))
    manual_estimate_val = _parse_currency(listing_row.get("manual_carsales_estimate"))
    manual_instant_offer_val = _parse_currency(listing_row.get("manual_instant_offer_estimate"))
    manual_recent_sales_val = _parse_int(listing_row.get("manual_recent_sales_30d"))

    active_odometer_val = _parse_odometer_value(listing_row.get("odometer_numeric"))
    if active_odometer_val is None:
        active_odometer_val = _parse_odometer_value(listing_row.get("odometer_reading"))

    base_manual_price = manual_estimate_val if manual_estimate_val is not None else manual_avg_val

    if (
        not force_refresh
        and url
        and url in set(cached_df["url"].dropna().tolist())
    ):
        existing = cached_df[cached_df["url"] == url].iloc[0].to_dict()
        existing["cached"] = True
        return existing

    client = _get_client()
    prompt = _build_prompt(listing_row.to_dict())
    def _extract_json_block(text: str) -> Optional[str]:
        if not text:
            return None
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if match:
            return match.group(0).strip()
        return None

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            messages=[
                {"role": "system", "content": "You are an expert automotive pricing analyst."},
                {"role": "user", "content": prompt},
            ],
        )
        raw_content = response.choices[0].message.content.strip()
        json_block = _extract_json_block(raw_content)
        if not json_block:
            raise ValueError(f"No JSON detected in response: {raw_content[:200]}")
        data = json.loads(json_block)
    except Exception as exc:
        return {
            "url": url,
            "error": f"AI analysis failed: {exc}",
        }

    notes = data.get("confidence_notes", [])
    if isinstance(notes, list):
        notes_value = "; ".join(notes)
    else:
        notes_value = str(notes)

    score_value = data.get("score_out_of_10")
    try:
        score_value = float(score_value) if score_value is not None else None
    except (TypeError, ValueError):
        score_value = None
    if score_value is not None:
        score_value = max(0.0, min(10.0, score_value))

    recommended_max_bid_val = _parse_currency(data.get("recommended_max_bid"))
    recommended_max_bid_str = data.get("recommended_max_bid")

    carsales_estimate = data.get("carsales_price_estimate")
    carsales_range = data.get("carsales_price_range")

    price_adjust_factor = 1.0
    adjusted_avg_price = base_manual_price
    adjustment_note = None
    if (
        base_manual_price is not None
        and manual_avg_odo_val is not None
        and active_odometer_val is not None
        and active_odometer_val > 0
    ):
        raw_factor = manual_avg_odo_val / active_odometer_val
        price_adjust_factor = max(0.25, min(raw_factor, 1.2))
        adjusted_avg_price = base_manual_price * price_adjust_factor
        if abs(price_adjust_factor - 1.0) > 0.05:
            adjustment_note = (
                f"Adjusted Carsales average for odometer difference (factor {price_adjust_factor:.2f})."
            )

    if base_manual_price is not None:
        if adjusted_avg_price is not None:
            carsales_estimate = _format_currency(adjusted_avg_price)
        else:
            carsales_estimate = _format_currency(base_manual_price)

    if manual_min_val is not None and manual_max_val is not None:
        if adjusted_avg_price is not None and base_manual_price:
            scaled_min = manual_min_val * price_adjust_factor
            scaled_max = manual_max_val * price_adjust_factor
            carsales_range = f"{_format_currency(scaled_min)} - {_format_currency(scaled_max)}"
        else:
            carsales_range = f"{_format_currency(manual_min_val)} - {_format_currency(manual_max_val)}"

    if adjusted_avg_price is None:
        parsed_estimate = _parse_currency(carsales_estimate)
        if parsed_estimate is None and carsales_range:
            parsed_estimate = _parse_currency(carsales_range)
        adjusted_avg_price = parsed_estimate

    break_even_bid = None
    if adjusted_avg_price is not None:
        break_even_bid = max(0.0, adjusted_avg_price - COST_BUFFER)

    current_price_val = _parse_currency(listing_row.get("current_price"))
    if current_price_val is None:
        current_price_val = _parse_currency(listing_row.get("price"))
    historical_min_val = _parse_currency(listing_row.get("historical_price_min"))
    historical_close_median_val = _parse_currency(listing_row.get("historical_close_price_median"))
    historical_close_min_val = _parse_currency(listing_row.get("historical_close_price_min"))

    notes_to_append: list[str] = []

    if recommended_max_bid_val is not None and price_adjust_factor != 1.0:
        recommended_max_bid_val = recommended_max_bid_val * price_adjust_factor

    if recommended_max_bid_val is None:
        if break_even_bid is not None:
            recommended_max_bid_val = break_even_bid
            notes_to_append.append(
                "AI response missing max bid; defaulted to break-even after $1,500 buffer."
            )
        else:
            fallback_candidates = [
                value for value in (historical_min_val, current_price_val) if value is not None
            ]
            if fallback_candidates:
                fallback_value = max(fallback_candidates)
                recommended_max_bid_val = fallback_value
                notes_to_append.append(
                    f"AI response missing max bid; using observed floor {_format_currency(fallback_value)}."
                )

    floor_value = current_price_val
    floor_reason = "current live bid" if current_price_val is not None else None
    historical_references: list[tuple[str, float]] = []
    for label, value in (
        ("historical auction minimum", historical_min_val),
        ("closest historical median", historical_close_median_val),
        ("historical close minimum", historical_close_min_val),
    ):
        if value is not None:
            historical_references.append((label, value))

    if break_even_bid is not None and recommended_max_bid_val is not None:
        if recommended_max_bid_val > break_even_bid:
            recommended_max_bid_val = break_even_bid

    if adjusted_avg_price is not None and recommended_max_bid_val is not None:
        recommended_max_bid_val = min(recommended_max_bid_val, adjusted_avg_price)

    if floor_value is not None:
        if recommended_max_bid_val is None:
            recommended_max_bid_val = floor_value
        elif recommended_max_bid_val < floor_value:
            recommended_max_bid_val = floor_value
            if floor_reason:
                notes_to_append.append(
                    f"Raised recommended max bid to match the {floor_reason} ({_format_currency(floor_value)})."
                )

    if (
        current_price_val is not None
        and recommended_max_bid_val is not None
        and CURRENT_BID_HEADROOM > 0
    ):
        headroom_cap = current_price_val + CURRENT_BID_HEADROOM
        if recommended_max_bid_val > headroom_cap:
            recommended_max_bid_val = headroom_cap
            notes_to_append.append(
                f"Capped recommended max bid at {_format_currency(headroom_cap)} (current bid plus ${CURRENT_BID_HEADROOM:,.0f} headroom)."
            )

    if recommended_max_bid_val is not None:
        for label, value in historical_references:
            if value is not None and recommended_max_bid_val < value:
                notes_to_append.append(
                    f"Recommended bid undercuts the {label} ({_format_currency(value)}); confirm condition advantages before bidding."
                )
                break

    if recommended_max_bid_val is not None:
        recommended_max_bid_val = max(0.0, recommended_max_bid_val)

    expected_profit_val = None
    if adjusted_avg_price is not None and recommended_max_bid_val is not None:
        expected_profit_val = adjusted_avg_price - COST_BUFFER - recommended_max_bid_val
        expected_profit_val = max(0.0, expected_profit_val)

    expected_profit = (
        _format_currency(expected_profit_val)
        if expected_profit_val is not None
        else data.get("expected_profit")
    )

    profit_margin = data.get("profit_margin_percent")
    margin_value: Optional[float] = None
    if expected_profit_val is not None and adjusted_avg_price:
        margin_value = (expected_profit_val / adjusted_avg_price) * 100 if adjusted_avg_price else 0
        profit_margin = f"{margin_value:.1f}%"

    if recommended_max_bid_val is not None:
        recommended_max_bid_str = _format_currency(recommended_max_bid_val)

    if adjustment_note:
        notes_to_append.append(adjustment_note)

    if expected_profit_val is not None:
        if expected_profit_val <= 0:
            if score_value is not None and score_value > 0:
                notes_to_append.append("Score forced to 0 because projected profit is not positive.")
            score_value = 0.0
        elif margin_value is not None:
            # Cap score based on realised profit margin to keep valuations consistent.
            score_cap = max(0.0, min(10.0, margin_value / 5.0))
            if score_value is None:
                score_value = score_cap
                notes_to_append.append(
                    f"Score derived from profit margin cap ({margin_value:.1f}% => {score_cap:.1f}/10)."
                )
            else:
                capped_score = min(score_value, score_cap)
                if capped_score < score_value - 1e-6:
                    notes_to_append.append(
                        f"Score capped at {capped_score:.1f} to align with {margin_value:.1f}% profit margin."
                    )
                score_value = capped_score

    if score_value is not None:
        score_value = round(float(score_value), 1)

    if notes_to_append:
        existing_notes = (
            [
                note.strip()
                for note in str(notes_value).split(";")
                if note.strip() and note.strip().lower() != "none"
            ]
            if notes_value
            else []
        )
        existing_notes.extend(notes_to_append)
        deduped_notes: list[str] = []
        for note in existing_notes:
            if note not in deduped_notes:
                deduped_notes.append(note)
        notes_value = "; ".join(deduped_notes) if deduped_notes else None

    result_row = {
        "url": url,
        "analysis_timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "carsales_price_estimate": carsales_estimate,
        "carsales_price_range": carsales_range,
        "recommended_max_bid": recommended_max_bid_str,
        "expected_profit": expected_profit,
        "profit_margin_percent": profit_margin,
        "score_out_of_10": score_value,
        "confidence_notes": notes_value,
        "manual_carsales_count": manual_count_val,
        "manual_carsales_min": _format_currency(manual_min_val) if manual_min_val is not None else None,
        "manual_carsales_max": _format_currency(manual_max_val) if manual_max_val is not None else None,
        "manual_carsales_avg": _format_currency(manual_avg_val) if manual_avg_val is not None else None,
        "manual_carsales_avg_odometer": _format_odometer(manual_avg_odo_val) if manual_avg_odo_val is not None else None,
        "manual_carsales_estimate": listing_row.get("manual_carsales_estimate"),
        "manual_instant_offer_estimate": listing_row.get("manual_instant_offer_estimate"),
        "manual_recent_sales_30d": listing_row.get("manual_recent_sales_30d"),
    }

    _save_result_row(result_row)
    result_row["cached"] = False
    return result_row
