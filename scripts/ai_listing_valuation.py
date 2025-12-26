import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import os
import pandas as pd
from dotenv import load_dotenv, find_dotenv
from openai import OpenAI

from shared.data_loader import DATA_DIR


AI_RESULTS_PATH = DATA_DIR / "ai_listing_valuations.csv"
REQUIRED_COLUMNS = [
    "url",
    "analysis_timestamp",
    # Risk-banded resale figures
    "resale_low",
    "resale_mid",
    "resale_high",
    # Profit / friction
    "net_profit_mid",
    "net_profit_worst",
    "fees_estimate",
    "transport_estimate",
    "rego_estimate",
    "prep_estimate",
    # Risk decisioning
    "confidence",
    "risk_flags",
    "verdict",
    # Legacy fields (kept for compatibility)
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
    "manual_carsales_estimate",
    "manual_recent_sales_30d",
    "manual_carsales_table",
]

# Default cost assumptions (AUD)
DEFAULT_TRANSPORT = 400.0
DEFAULT_PREP = 300.0
UNREGISTERED_REGO_COST = 1_200.0
REGISTERED_REGO_COST = 0.0
MIN_FEES = 500.0
FEES_RATE = 0.08
# Max headroom we give above the current live bid before we cap the recommendation.
CURRENT_BID_HEADROOM = 3_500.0
# Minimum net profit target and band controls
MIN_NET_PROFIT_ABSOLUTE = 1_500.0
MIN_NET_PROFIT_RATIO = 0.15
BASE_DOWNSIDE_PCT = 0.12
BASE_UPSIDE_PCT = 0.08
HIGH_KM_THRESHOLD = 180_000
CONFIDENCE_BASE = 0.8
CONFIDENCE_MIN = 0.1
CONFIDENCE_MAX = 0.9
RISK_CONFIDENCE_PENALTIES = {
    "WARNING_LIGHT": 0.12,
    "ENGINE_UNKNOWN": 0.1,
    "UNREGISTERED": 0.08,
    "HIGH_KM": 0.07,
    "NO_SERVICE_HISTORY": 0.05,
    "NO_MANUAL": 0.03,
    "MISSING_KEYS": 0.04,
}
RISK_NET_PROFIT_ADDERS = {
    "WARNING_LIGHT": 800.0,
    "ENGINE_UNKNOWN": 800.0,
    "UNREGISTERED": 500.0,
    "HIGH_KM": 400.0,
    "NO_SERVICE_HISTORY": 250.0,
    "NO_MANUAL": 150.0,
    "MISSING_KEYS": 200.0,
}

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


def _parse_int(value: Any) -> Optional[int]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(float(str(value).strip().replace(",", "")))
    except (TypeError, ValueError):
        return None


def _parse_odometer(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).lower().replace("km", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _is_unregistered(listing: Mapping[str, Any]) -> bool:
    expiry = str(listing.get("rego_expiry") or "").lower()
    rego_no = str(listing.get("rego_no") or "").strip().lower()
    if "unregistered" in expiry or "without plates" in expiry:
        return True
    if not expiry and (not rego_no or "no plates" in rego_no):
        return True
    return False


def _estimate_transport_cost(location: Any) -> float:
    if not location or (isinstance(location, float) and pd.isna(location)):
        return DEFAULT_TRANSPORT
    text = str(location).upper()
    cost = DEFAULT_TRANSPORT
    if any(state in text for state in ("WA", "NT")):
        cost += 300
    elif any(state in text for state in ("SA", "QLD", "TAS")):
        cost += 150
    return cost


def _estimate_costs(purchase_price: float, listing: Mapping[str, Any]) -> dict[str, float]:
    fees = max(MIN_FEES, purchase_price * FEES_RATE)
    transport = _estimate_transport_cost(listing.get("location"))
    rego = UNREGISTERED_REGO_COST if _is_unregistered(listing) else REGISTERED_REGO_COST
    prep = DEFAULT_PREP
    return {
        "fees_estimate": fees,
        "transport_estimate": transport,
        "rego_estimate": rego,
        "prep_estimate": prep,
    }


def _detect_risk_flags(listing: Mapping[str, Any]) -> list[str]:
    flags: list[str] = []
    odometer_value = _parse_odometer(
        listing.get("odometer_numeric") or listing.get("odometer_reading")
    )
    if odometer_value is not None and odometer_value >= HIGH_KM_THRESHOLD:
        flags.append("HIGH_KM")
    if _is_unregistered(listing):
        flags.append("UNREGISTERED")
    service_history = str(listing.get("service_history") or "").strip().lower()
    if service_history in {"no", "none", ""}:
        flags.append("NO_SERVICE_HISTORY")
    owners_manual = str(listing.get("owners_manual") or "").strip().lower()
    if owners_manual in {"no", "none", ""}:
        flags.append("NO_MANUAL")
    key = str(listing.get("key") or "").strip().lower()
    spare_key = str(listing.get("spare_key") or "").strip().lower()
    if key in {"no", "none", ""} or spare_key in {"no", "none", ""}:
        flags.append("MISSING_KEYS")
    engine_turns = str(listing.get("engine_turns_over") or "").strip().lower()
    if engine_turns in {"no", "none"}:
        flags.append("ENGINE_UNKNOWN")
    condition_text = str(listing.get("general_condition") or "").lower()
    if "warning" in condition_text or "engine light" in condition_text:
        flags.append("WARNING_LIGHT")
    return flags


def _calculate_confidence(listing: Mapping[str, Any], risk_flags: list[str]) -> float:
    confidence = CONFIDENCE_BASE
    comps = _parse_int(listing.get("historical_match_count"))
    if comps is None or comps == 0:
        confidence -= 0.2
    elif comps < 3:
        confidence -= 0.1
    if not listing.get("historical_matches_rows"):
        confidence -= 0.05
    risk_penalty = sum(RISK_CONFIDENCE_PENALTIES.get(flag, 0.04) for flag in risk_flags)
    confidence -= risk_penalty
    return max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, confidence))


def _calculate_downside_percent(risk_flags: list[str]) -> float:
    downside = BASE_DOWNSIDE_PCT
    for flag in risk_flags:
        if flag in {"HIGH_KM", "UNREGISTERED"}:
            downside += 0.05
        elif flag in {"NO_SERVICE_HISTORY", "NO_MANUAL", "MISSING_KEYS"}:
            downside += 0.03
        else:
            downside += 0.02
    return min(0.5, downside)


def _calculate_upside_percent(risk_flags: list[str]) -> float:
    upside = BASE_UPSIDE_PCT - (0.015 * len(risk_flags))
    return max(0.02, upside)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _has_any(haystack: str, needles: list[str]) -> bool:
    return any(needle in haystack for needle in needles)


def apply_platform_risk_adjustments(
    listing: Mapping[str, Any],
    downside_pct: float,
    confidence: float,
    risk_flags: list[str],
    notes: list[str],
) -> tuple[float, float, list[str], list[str]]:
    """
    Apply known platform/drivetrain risk penalties (DSG, Powershift, CVT, etc.).
    Returns adjusted (downside_pct, confidence, risk_flags, notes).
    """

    make = _norm(listing.get("make"))
    model = _norm(listing.get("model"))
    variant = _norm(listing.get("variant"))
    transmission = _norm(listing.get("transmission"))
    engine = _norm(listing.get("engine"))
    year_raw = listing.get("year")

    try:
        year = int(float(year_raw)) if year_raw not in (None, "") else None
    except Exception:
        year = None

    def add_flag(flag: str) -> None:
        if flag not in risk_flags:
            risk_flags.append(flag)

    def add_note(message: str) -> None:
        if message not in notes:
            notes.append(message)

    # VW/Audi/Skoda/Seat DSG (DQ200 era)
    if make in {"volkswagen", "audi", "skoda", "seat"} and _has_any(
        transmission, ["dsg", "dual clutch", "dct"]
    ):
        if year is None or year <= 2016:
            downside_pct += 0.25
            confidence -= 0.18
            add_flag("DSG_HIGH_RISK")
            add_note("Applied platform risk penalty: VW-group DSG (DQ200-era failure risk).")

    # Ford Powershift / DPS6
    if make == "ford" and _has_any(transmission, ["powershift", "dps6", "dual clutch", "dct"]):
        if year is None or year <= 2017:
            downside_pct += 0.30
            confidence -= 0.22
            add_flag("POWERSHIFT_HIGH_RISK")
            add_note("Applied platform risk penalty: Ford Powershift/DPS6 (known high-cost failures).")

    # Nissan/Mitsubishi/Subaru CVT risk heuristics
    if _has_any(transmission, ["cvt"]):
        if make in {"nissan", "mitsubishi", "subaru"} and (year is None or year <= 2016):
            downside_pct += 0.20
            confidence -= 0.15
            add_flag("CVT_HIGH_RISK")
            add_note("Applied platform risk penalty: CVT drivetrain risk for this year/make.")

    # Holden Alloytec timing chain heuristics
    if make == "holden" and (year is None or year <= 2012):
        if _has_any(model + " " + variant + " " + engine, ["commodore", "alloytec"]):
            downside_pct += 0.18
            confidence -= 0.12
            add_flag("ENGINE_HIGH_RISK")
            add_note("Applied platform risk penalty: Holden Alloytec timing chain exposure.")

    # BMW N13/N20 pre-2014 heuristics
    if make == "bmw" and (year is None or year <= 2014):
        if _has_any(model + " " + variant + " " + engine, ["116i", "118i", "320i", "n13", "n20"]):
            downside_pct += 0.12
            confidence -= 0.10
            add_flag("BMW_PRE2014_RISK")
            add_note("Applied platform risk penalty: BMW pre-2014 petrol timing/cooling risk.")

    downside_pct = max(0.05, min(0.60, downside_pct))
    confidence = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, confidence))
    return downside_pct, confidence, risk_flags, notes


def _net_profit_value(resale_value: float, bid: float, listing: Mapping[str, Any]) -> float:
    costs = _estimate_costs(bid, listing)
    total_cost = sum(costs.values())
    return resale_value - bid - total_cost


def _solve_max_bid(
    resale_low: Optional[float],
    min_net_profit: float,
    listing: Mapping[str, Any],
) -> float:
    if resale_low is None or resale_low <= 0:
        return 0.0
    if _net_profit_value(resale_low, 0.0, listing) < min_net_profit:
        return 0.0
    low = 0.0
    high = resale_low
    best = 0.0
    for _ in range(60):
        mid = (low + high) / 2.0
        net = _net_profit_value(resale_low, mid, listing)
        if net >= min_net_profit:
            best = mid
            low = mid
        else:
            high = mid
    return max(0.0, min(best, resale_low))


def _map_verdict(net_profit_worst: Optional[float], confidence: Optional[float]) -> str:
    if net_profit_worst is None or net_profit_worst <= 0 or confidence is None:
        return "Avoid"
    if net_profit_worst >= 2_500 and confidence >= 0.65:
        return "Sniper Buy"
    if net_profit_worst >= 1_200 and confidence >= 0.45:
        return "Flippable"
    if net_profit_worst > 0:
        return "Trap"
    return "Avoid"


def update_manual_carsales_data(
    url: str,
    price_estimate: Optional[str],
    table_raw: str,
    recent_sales_30d: Optional[int] = None,
    comparable_count: Optional[int] = None,
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
    df.at[idx, "manual_carsales_min"] = df.at[idx, "manual_carsales_estimate"]
    df.at[idx, "manual_carsales_max"] = df.at[idx, "manual_carsales_estimate"]
    df.at[idx, "manual_carsales_avg"] = df.at[idx, "manual_carsales_estimate"]
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
        "carsales_manual_estimate": listing.get("manual_carsales_estimate")
        or listing.get("manual_carsales_avg"),
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
    manual_estimate_val = _parse_currency(
        listing_row.get("manual_carsales_estimate") or listing_row.get("manual_carsales_avg")
    )
    manual_min_val = _parse_currency(listing_row.get("manual_carsales_min"))
    manual_max_val = _parse_currency(listing_row.get("manual_carsales_max"))
    manual_recent_sales_val = _parse_int(listing_row.get("manual_recent_sales_30d"))

    manual_avg_value = manual_estimate_val
    if manual_avg_value is None:
        if manual_min_val is not None and manual_max_val is not None:
            manual_avg_value = (manual_min_val + manual_max_val) / 2.0
        elif manual_min_val is not None:
            manual_avg_value = manual_min_val
        elif manual_max_val is not None:
            manual_avg_value = manual_max_val

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

    ai_carsales_estimate = _parse_currency(data.get("carsales_price_estimate"))
    ai_carsales_range = _parse_currency(data.get("carsales_price_range"))

    resale_mid_value = manual_avg_value or ai_carsales_estimate or ai_carsales_range
    if resale_mid_value is None:
        resale_mid_value = _parse_currency(listing_row.get("historical_price_median"))
    if resale_mid_value is None:
        resale_mid_value = _parse_currency(listing_row.get("historical_price_mean"))
    if resale_mid_value is None:
        resale_mid_value = _parse_currency(listing_row.get("historical_price_max"))
    if resale_mid_value is None:
        resale_mid_value = _parse_currency(listing_row.get("historical_price_min"))
    if resale_mid_value is None:
        resale_mid_value = _parse_currency(listing_row.get("current_price"))
    if resale_mid_value is None:
        return {"url": url, "error": "Unable to derive resale estimate."}

    notes_to_append: list[str] = []
    risk_flags = _detect_risk_flags(listing_row)
    confidence = _calculate_confidence(listing_row, risk_flags)
    downside_pct = _calculate_downside_percent(risk_flags)
    downside_pct, confidence, risk_flags, notes_to_append = apply_platform_risk_adjustments(
        listing_row.to_dict(),
        downside_pct,
        confidence,
        risk_flags,
        notes_to_append,
    )
    upside_pct = _calculate_upside_percent(risk_flags)
    resale_low_value = resale_mid_value * (1 - downside_pct)
    resale_high_value = resale_mid_value * (1 + upside_pct)

    carsales_estimate = _format_currency(resale_mid_value)
    carsales_range = f"{_format_currency(resale_low_value)} - {_format_currency(resale_high_value)}"

    risk_profit_buffer = sum(RISK_NET_PROFIT_ADDERS.get(flag, 0.0) for flag in risk_flags)
    absolute_floor = MIN_NET_PROFIT_ABSOLUTE + risk_profit_buffer
    ratio_floor = resale_mid_value * MIN_NET_PROFIT_RATIO + risk_profit_buffer
    min_net_profit = max(absolute_floor, ratio_floor)

    recommended_max_bid_val = _solve_max_bid(resale_low_value, min_net_profit, listing_row)
    break_even_bid = _solve_max_bid(resale_low_value, 0.0, listing_row)

    current_price_val = _parse_currency(listing_row.get("current_price"))
    if current_price_val is None:
        current_price_val = _parse_currency(listing_row.get("price"))
    historical_min_val = _parse_currency(listing_row.get("historical_price_min"))
    historical_close_median_val = _parse_currency(listing_row.get("historical_close_price_median"))
    historical_close_min_val = _parse_currency(listing_row.get("historical_close_price_min"))

    floor_value = current_price_val
    historical_references: list[tuple[str, float]] = []
    for label, value in (
        ("historical auction minimum", historical_min_val),
        ("closest historical median", historical_close_median_val),
        ("historical close minimum", historical_close_min_val),
    ):
        if value is not None:
            historical_references.append((label, value))

    def _would_be_unprofitable_if_raised(floor_bid: float | None, break_even: float | None) -> bool:
        if floor_bid is None:
            return False
        if break_even is None:
            return True
        return floor_bid > break_even + 1e-6

    if floor_value is not None:
        if recommended_max_bid_val is None or recommended_max_bid_val <= 0:
            if _would_be_unprofitable_if_raised(floor_value, break_even_bid):
                if break_even_bid is not None and break_even_bid > 0:
                    recommended_max_bid_val = max(0.0, break_even_bid)
                    notes_to_append.append(
                        f"Did not set max bid to current bid ({_format_currency(floor_value)}) because it exceeds break-even "
                        f"({(_format_currency(break_even_bid) or '--')})."
                    )
                else:
                    notes_to_append.append(
                        f"Did not set max bid to current bid ({_format_currency(floor_value)}) because break-even could not be established."
                    )
            else:
                recommended_max_bid_val = floor_value
        elif recommended_max_bid_val < floor_value:
            if _would_be_unprofitable_if_raised(floor_value, break_even_bid):
                notes_to_append.append(
                    f"Kept safe max bid at {_format_currency(recommended_max_bid_val)}; current bid "
                    f"({_format_currency(floor_value)}) exceeds break-even ({(_format_currency(break_even_bid) or '--')})."
                )
            else:
                recommended_max_bid_val = floor_value
                notes_to_append.append(
                    f"Raised recommended max bid to match the current live bid ({_format_currency(floor_value)})."
                )

    if floor_value is not None and break_even_bid is not None and floor_value > break_even_bid:
        notes_to_append.append("Current bid exceeds break-even; treat as Avoid unless price drops.")

    if (
        current_price_val is not None
        and CURRENT_BID_HEADROOM > 0
        and recommended_max_bid_val > current_price_val + CURRENT_BID_HEADROOM
    ):
        headroom_cap = current_price_val + CURRENT_BID_HEADROOM
        recommended_max_bid_val = headroom_cap
        notes_to_append.append(
            f"Capped recommended max bid at {_format_currency(headroom_cap)} (current bid plus ${CURRENT_BID_HEADROOM:,.0f} headroom)."
        )

    if recommended_max_bid_val > resale_low_value:
        recommended_max_bid_val = resale_low_value

    for label, value in historical_references:
        if value is not None and recommended_max_bid_val < value:
            notes_to_append.append(
                f"Recommended bid undercuts the {label} ({_format_currency(value)}); confirm condition advantages before bidding."
            )
            break

    recommended_max_bid_val = max(0.0, recommended_max_bid_val)
    costs_map = _estimate_costs(recommended_max_bid_val, listing_row)
    total_costs = sum(costs_map.values())
    net_profit_worst_val = resale_low_value - recommended_max_bid_val - total_costs
    net_profit_mid_val = resale_mid_value - recommended_max_bid_val - total_costs

    expected_profit = _format_currency(net_profit_mid_val)
    margin_value = (net_profit_mid_val / resale_mid_value) * 100 if resale_mid_value else None
    profit_margin = f"{margin_value:.1f}%" if margin_value is not None else None
    recommended_max_bid_str = _format_currency(recommended_max_bid_val)

    verdict = _map_verdict(net_profit_worst_val, confidence)

    high_risk_platform_flags = {"DSG_HIGH_RISK", "POWERSHIFT_HIGH_RISK", "CVT_HIGH_RISK"}
    platform_high_risk = any(flag in high_risk_platform_flags for flag in risk_flags)
    forced_verdict: Optional[str] = None
    if platform_high_risk:
        if net_profit_worst_val is not None and net_profit_worst_val < 0:
            forced_verdict = "Avoid"
        elif net_profit_worst_val is not None and net_profit_worst_val < 2_500:
            forced_verdict = "Trap"
        elif confidence < 0.45:
            forced_verdict = "Trap"
        if forced_verdict and forced_verdict != verdict:
            verdict = forced_verdict
            notes_to_append.append(
                "Forced verdict downgrade due to drivetrain risk (DSG/Powershift/CVT heuristics)."
            )

    if net_profit_mid_val <= 0:
        score_value = 0.0
    elif margin_value is not None:
        score_cap = max(0.0, min(10.0, margin_value / 5.0))
        if score_value is None:
            score_value = score_cap
        else:
            score_value = min(score_value, score_cap)

    if score_value is not None:
        score_value = round(float(score_value), 1)

    notes_to_append.append(f"Applied {downside_pct*100:.0f}% downside band for worst-case pricing.")
    if net_profit_worst_val < min_net_profit:
        notes_to_append.append("Worst-case net profit below target; treat as high-risk.")

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

    manual_estimate_display = _format_currency(manual_estimate_val)
    manual_min_display = _format_currency(manual_min_val)
    manual_max_display = _format_currency(manual_max_val)
    manual_avg_display = _format_currency(manual_avg_value) if manual_avg_value is not None else manual_estimate_display

    result_row = {
        "url": url,
        "analysis_timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "resale_low": _format_currency(resale_low_value),
        "resale_mid": _format_currency(resale_mid_value),
        "resale_high": _format_currency(resale_high_value),
        "net_profit_mid": _format_currency(net_profit_mid_val),
        "net_profit_worst": _format_currency(net_profit_worst_val),
        "fees_estimate": _format_currency(costs_map["fees_estimate"]),
        "transport_estimate": _format_currency(costs_map["transport_estimate"]),
        "rego_estimate": _format_currency(costs_map["rego_estimate"]),
        "prep_estimate": _format_currency(costs_map["prep_estimate"]),
        "confidence": round(confidence, 3),
        "risk_flags": "|".join(risk_flags) if risk_flags else None,
        "verdict": verdict,
        "carsales_price_estimate": carsales_estimate,
        "carsales_price_range": carsales_range,
        "recommended_max_bid": recommended_max_bid_str,
        "expected_profit": expected_profit,
        "profit_margin_percent": profit_margin,
        "score_out_of_10": score_value,
        "confidence_notes": notes_value,
        "manual_carsales_count": manual_count_val,
        "manual_carsales_min": manual_min_display,
        "manual_carsales_max": manual_max_display,
        "manual_carsales_avg": manual_avg_display,
        "manual_carsales_estimate": listing_row.get("manual_carsales_estimate") or manual_estimate_display,
        "manual_recent_sales_30d": listing_row.get("manual_recent_sales_30d"),
        "manual_carsales_table": listing_row.get("manual_carsales_table"),
    }

    _save_result_row(result_row)
    result_row["cached"] = False
    return result_row
