import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import os
import pandas as pd
from dotenv import load_dotenv, find_dotenv
from openai import OpenAI

from shared.data_loader import dataset_path


AI_RESULTS_PATH = dataset_path("ai_listing_valuations.csv")
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
    "computed_verdict",
    "no_edge",
    "edge_note",
    "edge_buffer",
    # Legacy fields (kept for compatibility)
    "carsales_price_estimate",
    "carsales_price_range",
    "recommended_max_bid",
    "expected_profit",
    "profit_margin_percent",
    "score_out_of_10",
    "confidence_notes",
]

# Default cost assumptions (AUD)
DEFAULT_TRANSPORT = 400.0
DEFAULT_PREP = 300.0
COST_BUFFER = 1_500.0
UNREGISTERED_REGO_COST = 1_200.0
REGISTERED_REGO_COST = 0.0
MIN_FEES = 500.0
FEES_RATE = 0.08
# Max headroom we give above the current live bid before we cap the recommendation.
CURRENT_BID_HEADROOM = 3_500.0
EDGE_BUFFER = 50.0
WORST_CASE_DOWNSIDE = 0.17  # 17% downside band used for worst-case resale
NO_EDGE_MESSAGE = "No edge left at current bid — do not bid above {amount}."


def _round_to_10(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value / 10.0) * 10.0


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

    if recommended_max_bid_val is None:
        if break_even_bid is not None:
            recommended_max_bid_val = break_even_bid
            notes_to_append.append("AI response missing max bid; defaulted to break-even after $1,500 buffer.")
        else:
            fallback_candidates = [value for value in (historical_min_val, current_price_val) if value is not None]
            if fallback_candidates:
                fallback_value = max(fallback_candidates)
                recommended_max_bid_val = fallback_value
                notes_to_append.append(f"AI response missing max bid; using observed floor {_format_currency(fallback_value)}.")

    if break_even_bid is not None and recommended_max_bid_val is not None and recommended_max_bid_val > break_even_bid:
        recommended_max_bid_val = break_even_bid

    if adjusted_avg_price is not None and recommended_max_bid_val is not None:
        recommended_max_bid_val = min(recommended_max_bid_val, adjusted_avg_price)

    raised_to_match_current_bid = False
    if current_price_val is not None:
        if recommended_max_bid_val is None:
            recommended_max_bid_val = current_price_val
            raised_to_match_current_bid = True
        elif recommended_max_bid_val < current_price_val:
            recommended_max_bid_val = current_price_val
            raised_to_match_current_bid = True
            notes_to_append.append(f"Raised recommended max bid to match the current live bid {_format_currency(current_price_val)}.")

    if current_price_val is not None and recommended_max_bid_val is not None and CURRENT_BID_HEADROOM > 0:
        headroom_cap = current_price_val + CURRENT_BID_HEADROOM
        if recommended_max_bid_val > headroom_cap:
            recommended_max_bid_val = headroom_cap
            notes_to_append.append(
                f"Capped recommended max bid at {_format_currency(headroom_cap)} (current bid plus ${CURRENT_BID_HEADROOM:,.0f} headroom)."
            )

    historical_references: list[tuple[str, float]] = []
    for label, value in (
        ("historical auction minimum", historical_min_val),
        ("closest historical median", historical_close_median_val),
        ("historical close minimum", historical_close_min_val),
    ):
        if value is not None:
            historical_references.append((label, value))

    if recommended_max_bid_val is not None:
        for label, value in historical_references:
            if value is not None and recommended_max_bid_val < value:
                notes_to_append.append(
                    f"Recommended bid undercuts the {label} ({_format_currency(value)}); confirm condition advantages before bidding."
                )
                break

    if recommended_max_bid_val is not None:
        recommended_max_bid_val = max(0.0, recommended_max_bid_val)

    assumed_purchase_val = recommended_max_bid_val
    if assumed_purchase_val is None:
        assumed_purchase_val = current_price_val

    resale_mid_val = adjusted_avg_price
    resale_low_val = None
    resale_high_val = None
    if resale_mid_val is not None:
        resale_low_val = resale_mid_val * (1.0 - WORST_CASE_DOWNSIDE)
        resale_high_val = resale_mid_val * 1.07

    resale_mid_val = _round_to_10(resale_mid_val)
    resale_low_val = _round_to_10(resale_low_val)
    resale_high_val = _round_to_10(resale_high_val)

    net_profit_mid_val = None
    net_profit_worst_val = None
    if assumed_purchase_val is not None and resale_mid_val is not None:
        net_profit_mid_val = resale_mid_val - COST_BUFFER - assumed_purchase_val
    if assumed_purchase_val is not None and resale_low_val is not None:
        net_profit_worst_val = resale_low_val - COST_BUFFER - assumed_purchase_val

    expected_profit_val = None
    if resale_mid_val is not None and recommended_max_bid_val is not None:
        expected_profit_val = resale_mid_val - COST_BUFFER - recommended_max_bid_val

    expected_profit_val = max(0.0, expected_profit_val or 0.0) if expected_profit_val is not None else None
    expected_profit = _format_currency(expected_profit_val) if expected_profit_val is not None else data.get("expected_profit")

    profit_margin = data.get("profit_margin_percent")
    margin_value: Optional[float] = None
    if expected_profit_val is not None and resale_mid_val:
        margin_value = (expected_profit_val / resale_mid_val) * 100 if resale_mid_val else 0
        profit_margin = f"{margin_value:.1f}%"

    if recommended_max_bid_val is not None:
        recommended_max_bid_str = _format_currency(recommended_max_bid_val)

    confidence_val = None
    if score_value is not None:
        confidence_val = max(0.0, min(1.0, float(score_value) / 10.0))
    else:
        confidence_val = 0.45

    risk_flags: list[str] = []
    rego_state_val = str(listing_row.get("rego_state") or listing_row.get("registration_state") or "").strip()
    if not rego_state_val:
        risk_flags.append("UNREGISTERED")
    condition_text = str(listing_row.get("general_condition") or "").lower()
    condition_notes_text = str(listing_row.get("condition_notes") or "").lower()
    warning_keywords = ("warning", "warning light", "engine light", "check engine", "cel", "abs", "airbag")
    if any(keyword in condition_text or keyword in condition_notes_text for keyword in warning_keywords):
        risk_flags.append("WARNING_LIGHT")
    make_val = str(listing_row.get("make") or "").lower()
    year_val = _parse_int(listing_row.get("year"))
    if make_val == "bmw" and year_val is not None and year_val < 2014:
        risk_flags.append("BMW_PRE2014_RISK")

    warning_light_flag = (
        "WARNING_LIGHT" in risk_flags
        or "warning light" in condition_text
        or "warning light" in condition_notes_text
    )
    if warning_light_flag:
        if confidence_val is not None:
            confidence_val = max(0.0, confidence_val - 0.12)
        if net_profit_worst_val is not None:
            net_profit_worst_val -= 2000.0
        wl_note = "Warning light present → mechanical uncertainty penalty applied."
        if wl_note not in notes_to_append:
            notes_to_append.append(wl_note)

        fuel_text = str(listing_row.get("fuel_type") or "").lower()
        title_text = " ".join(
            filter(
                None,
                [
                    str(listing_row.get("title") or ""),
                    str(listing_row.get("variant") or ""),
                    str(listing_row.get("model") or ""),
                ],
            )
        ).lower()
        diesel_warning = "diesel" in fuel_text or "diesel" in title_text
        if diesel_warning:
            if confidence_val is not None:
                confidence_val = max(0.0, confidence_val - 0.05)
            if net_profit_worst_val is not None:
                net_profit_worst_val -= 1500.0
            diesel_note = "Diesel + warning light → higher expected repair risk."
            if diesel_note not in notes_to_append:
                notes_to_append.append(diesel_note)

    current_bid_val = current_price_val

    no_edge_at_current_bid = False
    if recommended_max_bid_val is not None and current_bid_val is not None:
        no_edge_at_current_bid = recommended_max_bid_val <= current_bid_val + EDGE_BUFFER
    edge_note = ""
    if no_edge_at_current_bid and "NO_EDGE" not in risk_flags:
        risk_flags.append("NO_EDGE")
    if no_edge_at_current_bid:
        edge_amount = _format_currency(recommended_max_bid_val) if recommended_max_bid_val is not None else None
        if not edge_amount:
            edge_amount = "--"
        edge_note_text = NO_EDGE_MESSAGE.format(amount=edge_amount)
        edge_note = edge_note_text
        if edge_note_text not in notes_to_append:
            notes_to_append.append(edge_note_text)

    def _derive_verdict() -> str:
        conf_value = confidence_val if confidence_val is not None else 0.0
        if net_profit_worst_val is None:
            return "Trap"
        if net_profit_worst_val <= 0:
            return "Avoid"
        if no_edge_at_current_bid:
            return "Trap"
        if conf_value >= 0.70 and net_profit_worst_val >= 3000:
            return "Strong Flip"
        if conf_value >= 0.55 and net_profit_worst_val > 0:
            return "Conditional Flip"
        return "Trap"

    computed_verdict = _derive_verdict()

    if notes_to_append:
        existing_notes = (
            [note.strip() for note in str(notes_value).split(";") if note.strip() and note.strip().lower() != "none"]
            if notes_value
            else []
        )
        existing_notes.extend(notes_to_append)
        deduped_notes: list[str] = []
        for note in existing_notes:
            if note not in deduped_notes:
                deduped_notes.append(note)
        notes_value = "; ".join(deduped_notes) if deduped_notes else None

    cost_basis = recommended_max_bid_val
    if cost_basis is None:
        cost_basis = current_price_val
    if cost_basis is None:
        cost_basis = 0.0
    costs_map = _estimate_costs(cost_basis, listing_row)

    risk_flags_str = "|".join(sorted(set(risk_flags))) if risk_flags else ""

    result_row = {
        "url": url,
        "analysis_timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "carsales_price_estimate": carsales_estimate,
        "carsales_price_range": carsales_range,
        "recommended_max_bid": recommended_max_bid_str,
        "expected_profit": expected_profit,
        "profit_margin_percent": profit_margin,
        "score_out_of_10": round(float(score_value), 1) if score_value is not None else None,
        "confidence_notes": notes_value,
        "fees_estimate": _format_currency(costs_map["fees_estimate"]),
        "transport_estimate": _format_currency(costs_map["transport_estimate"]),
        "rego_estimate": _format_currency(costs_map["rego_estimate"]),
        "prep_estimate": _format_currency(costs_map["prep_estimate"]),
        "resale_low": _format_currency(resale_low_val),
        "resale_mid": _format_currency(resale_mid_val),
        "resale_high": _format_currency(resale_high_val),
        "net_profit_mid": _format_currency(net_profit_mid_val) if net_profit_mid_val is not None else None,
        "net_profit_worst": _format_currency(net_profit_worst_val) if net_profit_worst_val is not None else None,
        "confidence": round(float(confidence_val), 3) if confidence_val is not None else None,
        "risk_flags": risk_flags_str,
        "computed_verdict": computed_verdict,
        "verdict": computed_verdict,
        "no_edge": bool(no_edge_at_current_bid),
        "edge_note": edge_note if no_edge_at_current_bid else "",
        "no_edge_at_current_bid": bool(no_edge_at_current_bid),
        "edge_buffer": EDGE_BUFFER,
    }

    _save_result_row(result_row)
    result_row["cached"] = False
    return result_row


def run_curve_listing_analysis(
    listing_row: pd.Series,
    resale_mid: float | None,
    *,
    comps_median: float | None = None,
    comps_count: int | None = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    cached_df = load_cached_results()
    url = listing_row.get("url")

    if (
        not force_refresh
        and url
        and url in set(cached_df["url"].dropna().tolist())
    ):
        existing = cached_df[cached_df["url"] == url].iloc[0].to_dict()
        existing["cached"] = True
        return existing

    if resale_mid is None or resale_mid <= 0:
        return {
            "url": url,
            "error": "No curve estimate available.",
        }

    listing_data = listing_row.to_dict()
    if comps_count is not None:
        listing_data["historical_match_count"] = comps_count
        listing_data["historical_matches_rows"] = comps_count

    risk_flags = _detect_risk_flags(listing_data)
    downside_pct = _calculate_downside_percent(risk_flags)
    upside_pct = _calculate_upside_percent(risk_flags)
    confidence_val = _calculate_confidence(listing_data, risk_flags)
    notes: list[str] = []
    downside_pct, confidence_val, risk_flags, notes = apply_platform_risk_adjustments(
        listing_data, downside_pct, confidence_val, risk_flags, notes
    )
    confidence_val = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, confidence_val))

    resale_low_val = resale_mid * (1.0 - downside_pct)
    resale_high_val = resale_mid * (1.0 + upside_pct)

    resale_mid_val = _round_to_10(resale_mid)
    resale_low_val = _round_to_10(resale_low_val)
    resale_high_val = _round_to_10(resale_high_val)

    min_net_profit = max(MIN_NET_PROFIT_ABSOLUTE, MIN_NET_PROFIT_RATIO * (resale_low_val or resale_mid))
    recommended_max_bid_val = _solve_max_bid(resale_low_val, min_net_profit, listing_data)

    current_price_val = _parse_currency(listing_row.get("price"))
    if current_price_val is not None and recommended_max_bid_val is not None:
        if recommended_max_bid_val < current_price_val:
            recommended_max_bid_val = current_price_val

    no_edge_at_current_bid = False
    if recommended_max_bid_val is not None and current_price_val is not None:
        no_edge_at_current_bid = recommended_max_bid_val <= current_price_val + EDGE_BUFFER

    cost_basis = recommended_max_bid_val or current_price_val or 0.0
    costs_map = _estimate_costs(cost_basis, listing_data)

    net_profit_mid_val = None
    net_profit_worst_val = None
    if recommended_max_bid_val is not None:
        net_profit_mid_val = _net_profit_value(resale_mid_val or resale_mid, recommended_max_bid_val, listing_data)
        net_profit_worst_val = _net_profit_value(resale_low_val or resale_mid, recommended_max_bid_val, listing_data)

    expected_profit_val = net_profit_mid_val
    expected_profit = _format_currency(expected_profit_val) if expected_profit_val is not None else None

    profit_margin = None
    if expected_profit_val is not None and resale_mid_val:
        profit_margin = f"{(expected_profit_val / resale_mid_val) * 100:.1f}%"

    def _derive_verdict() -> str:
        if resale_low_val is None:
            return "Not Covered"
        if net_profit_worst_val is None or net_profit_worst_val <= 0:
            return "Avoid"
        if no_edge_at_current_bid:
            return "Trap"
        if confidence_val >= 0.70 and net_profit_worst_val >= 3000:
            return "Strong Flip"
        if confidence_val >= 0.55 and net_profit_worst_val > 0:
            return "Conditional Flip"
        return "Trap"

    computed_verdict = _derive_verdict()
    edge_note = ""
    if no_edge_at_current_bid:
        edge_note = NO_EDGE_MESSAGE.format(
            amount=_format_currency(recommended_max_bid_val) if recommended_max_bid_val is not None else "--"
        )

    score_out_of_10 = round(float(confidence_val) * 10.0, 1) if confidence_val is not None else None

    risk_flags_str = "|".join(sorted(set(risk_flags))) if risk_flags else ""
    notes_value = "; ".join(notes) if notes else None
    result_row = {
        "url": url,
        "analysis_timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "carsales_price_estimate": _format_currency(resale_mid_val),
        "carsales_price_range": (
            f"{_format_currency(resale_low_val)} - {_format_currency(resale_high_val)}"
            if resale_low_val is not None and resale_high_val is not None
            else None
        ),
        "recommended_max_bid": _format_currency(recommended_max_bid_val) if recommended_max_bid_val is not None else None,
        "expected_profit": expected_profit,
        "profit_margin_percent": profit_margin,
        "score_out_of_10": score_out_of_10,
        "confidence_notes": notes_value,
        "fees_estimate": _format_currency(costs_map["fees_estimate"]),
        "transport_estimate": _format_currency(costs_map["transport_estimate"]),
        "rego_estimate": _format_currency(costs_map["rego_estimate"]),
        "prep_estimate": _format_currency(costs_map["prep_estimate"]),
        "resale_low": _format_currency(resale_low_val),
        "resale_mid": _format_currency(resale_mid_val),
        "resale_high": _format_currency(resale_high_val),
        "net_profit_mid": _format_currency(net_profit_mid_val) if net_profit_mid_val is not None else None,
        "net_profit_worst": _format_currency(net_profit_worst_val) if net_profit_worst_val is not None else None,
        "confidence": round(float(confidence_val), 3) if confidence_val is not None else None,
        "risk_flags": risk_flags_str,
        "computed_verdict": computed_verdict,
        "verdict": computed_verdict,
        "no_edge": bool(no_edge_at_current_bid),
        "edge_note": edge_note,
        "no_edge_at_current_bid": bool(no_edge_at_current_bid),
        "edge_buffer": EDGE_BUFFER,
    }

    _save_result_row(result_row)
    result_row["cached"] = False
    return result_row
