import json
import os
import re
import warnings
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlencode

import pandas as pd

from scripts.atomic_csv import append_dict_rows_csv_atomic, write_dataframe_csv_atomic
from shared.auction_model import predict_auction_price
from shared.data_loader import dataset_path
from shared.decision_policy import DecisionPolicyInput, derive_action_label, derive_action_label_from_row
from shared.repair_pricing import V2_DICTIONARY_PATH, assess_repairs, apply_repairs_to_max_bid
from shared.repair_review import DECISIONS_PATH
from shared.repair_features import build_repair_features, serialize_tags, REPAIR_CATEGORIES
from shared.reauction import adjusted_expected_auction_price
from shared.telegram_alerts import get_alert_state, send_on_state_change


AI_RESULTS_PATH = dataset_path("ai_listing_valuations.csv")
DECISION_EVENTS_PATH = dataset_path("ai/listing_decision_events.csv")
ACTIVE_LISTINGS_PATH = dataset_path("active_vehicle_details.csv")
SOLD_LISTINGS_PATH = dataset_path("sold_cars.csv")
REFERRED_LISTINGS_PATH = dataset_path("referred_cars.csv")
DEFAULT_AUTOSNIPER_APP_URL = "http://localhost:8501"
REQUIRED_COLUMNS = [
    "url",
    "year",
    "make",
    "model",
    "variant",
    "location",
    "analysis_timestamp",
    "analysis_context",
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
    "roadworthy_estimate",
    "prep_estimate",
    "repair_estimate",
    "unresolved_repair_count",
    "unresolved_repairs",
    "potential_buy_unresolved_repairs",
    "expected_auction_price",
    "expected_auction_bid_basis",
    "expected_auction_profit",
    "expected_auction_worst_profit",
    "expected_auction_source",
    "expected_auction_comps_count",
    "expected_auction_reauction_adjustment",
    "expected_auction_reauction_reason",
    "reauction_event_count",
    "reauction_last_price",
    "reauction_price_delta",
    "economic_max_bid",
    "economic_profit_mid",
    "economic_profit_worst",
    "economic_profit_at_current_bid",
    "economic_profit_at_current_bid_worst",
    "bid_policy_gate",
    "discount_used",
    "profit_at_current_bid",
    "profit_at_current_bid_worst",
    "current_profit_score",
    "current_profit_label",
    "expected_auction_profit_label",
    "hard_max_safety",
    "flip_difficulty",
    "difficulty_reasons",
    "bid_status",
    "action_label",
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
    "current_bid",
    "current_bid_numeric",
    "previous_current_bid",
    "previous_current_bid_numeric",
    "price_change_delta",
    "price_change_direction",
    "price_changed_at",
    "bids_observed",
    "time_remaining_observed",
    "valuation_input_hash",
    "resale_low_value",
    "resale_mid_value",
    "resale_high_value",
    "recommended_max_bid_value",
    "economic_max_bid_value",
    "net_profit_mid_value",
    "net_profit_worst_value",
    "expected_auction_price_value",
    "expected_auction_bid_basis_value",
    "expected_auction_profit_value",
    "expected_auction_worst_profit_value",
    "profit_at_current_bid_value",
    "profit_at_current_bid_worst_value",
    "profit_margin_value",
]
DECISION_EVENT_COLUMNS = [
    "event_at",
    "url",
    "year",
    "make",
    "model",
    "variant",
    "location",
    "event_types",
    "direction",
    "previous_verdict",
    "new_verdict",
    "previous_action",
    "new_action",
    "previous_max_bid",
    "new_max_bid",
    "previous_current_bid",
    "new_current_bid",
    "previous_bid_status",
    "new_bid_status",
    "previous_repair_estimate",
    "new_repair_estimate",
    "previous_risk_flags",
    "new_risk_flags",
    "previous_coverage_status",
    "new_coverage_status",
    "change_reason_summary",
]
DECISION_EVENT_MAX_BID_THRESHOLD = 250.0
DECISION_EVENT_REPAIR_THRESHOLD = 250.0
DECISION_EVENT_CURRENT_BID_THRESHOLD = 250.0

# Default cost assumptions (AUD)
DEFAULT_TRANSPORT = 200.0
# Interstate depot-to-depot transport into the operating state (VIC base).
# Conservative (upper-range, ute/4WD-sized) figures from 2026 carrier guides:
# Melbourne-Sydney-Brisbane lanes ~$450-$850, Brisbane->Melbourne ~$570-$1,080,
# Melbourne-Perth ~$2,000+, Tasmania adds ~$500-$1,000 ferry component.
INTERSTATE_TRANSPORT_COSTS = {
    "NSW": 800.0,
    "ACT": 750.0,
    "SA": 700.0,
    "QLD": 1_250.0,
    "TAS": 1_500.0,
    "WA": 2_300.0,
    "NT": 2_500.0,
}
INTERSTATE_TRANSPORT_DEFAULT = 1_250.0
OPERATING_STATE = os.getenv("AUTOSNIPER_OPERATING_STATE", "VIC").strip().upper() or "VIC"
_INTERSTATE_ENV_RAW = os.getenv("AUTOSNIPER_ALLOW_INTERSTATE_BUYING", "").strip().lower()
_INTERSTATE_TRUE_TOKENS = {"1", "true", "yes", "y"}
_INTERSTATE_FALSE_TOKENS = {"", "0", "false", "no", "n", "off"}
INTERSTATE_BUYING_ALLOWED = _INTERSTATE_ENV_RAW not in _INTERSTATE_FALSE_TOKENS
# Optional per-state allowlist: AUTOSNIPER_ALLOW_INTERSTATE_BUYING="nsw,qld,sa"
# enables interstate buying for those states only; "1/true/yes" allows all states.
INTERSTATE_ALLOWED_STATES: frozenset[str] | None = None
if INTERSTATE_BUYING_ALLOWED and _INTERSTATE_ENV_RAW not in _INTERSTATE_TRUE_TOKENS:
    INTERSTATE_ALLOWED_STATES = frozenset(
        token.strip().upper()
        for token in _INTERSTATE_ENV_RAW.replace(";", ",").split(",")
        if token.strip()
    ) or None
DEFAULT_PREP = 300.0
ROADWORTHY_ESTIMATE = float(os.getenv("AUTOSNIPER_ROADWORTHY_ESTIMATE", "250").strip() or "250")
DETAILING_HATCH_SEDAN = 99.0
DETAILING_SMALL_SUV_WAGON = 115.0
DETAILING_LARGE_SUV_4WD = 129.0
DEFAULT_DISCOUNT = 0.75
MIN_EXPECTED_AUCTION_COMPS = 3
COST_BUFFER = 1_500.0
REGISTERED_REGO_COST = 0.0
MIN_FEES = 500.0
FEES_RATE = 0.08
# Max headroom we give above the current live bid before we cap the recommendation.
CURRENT_BID_HEADROOM = 3_500.0
EDGE_BUFFER = 50.0
WORST_CASE_DOWNSIDE = 0.17  # 17% downside band used for worst-case resale
NO_EDGE_MESSAGE = "No edge left at current bid — do not bid above {amount}."
AUTOTRADER_CURVE_WARNING_THRESHOLD = 0.10
AUTOTRADER_CURVE_WARNING_FLAG = "AUTOTRADER_CURVE_MISMATCH"
FAST_MARKET_CLEAR_DAYS = 5
STALE_MARKET_DAYS = 30
FAST_MARKET_CLEAR_MIN_COUNT = 2
STALE_MARKET_MIN_COUNT = 3
FAST_MARKET_CLEAR_CONFIDENCE_BOOST = 0.08
STALE_MARKET_CONFIDENCE_PENALTY = 0.08
STALE_MARKET_FLAG = "STALE_RETAIL_MARKET"


def _round_to_10(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value / 10.0) * 10.0


# Minimum net profit target and band controls
# Calibrated 2026-07 against 548 restricted sold rows (scripts/calibration_report.py):
# 1500/0.15/0.12 -> 28 wins, $169k captured; 1000/0.10/0.08 -> 53 wins, $258k captured,
# 0 overbid-risk rows, min single-deal profit $2,089, robust to -20% curve error.
MIN_NET_PROFIT_ABSOLUTE = 1_000.0
MIN_NET_PROFIT_RATIO = 0.10
MIN_EXPECTED_PROFIT_VIABILITY = 2_000.0
BASE_DOWNSIDE_PCT = 0.08
BASE_UPSIDE_PCT = 0.08
HIGH_KM_THRESHOLD = 180_000
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0
CURVE_COVERAGE_WEIGHT = 0.40
REPAIR_CERTAINTY_WEIGHT = 0.30
DATA_COMPLETENESS_WEIGHT = 0.30
CONFIDENCE_RISK_PENALTY_SCALE = 0.35
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


def load_cached_results() -> pd.DataFrame:
    if not AI_RESULTS_PATH.exists():
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    try:
        df = pd.read_csv(AI_RESULTS_PATH)
    except Exception as exc:
        print(f"WARNING: could not read cached AI results {AI_RESULTS_PATH}: {type(exc).__name__}: {exc}")
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    for column in missing:
        df[column] = None
    return df


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _current_bid_value(row: Mapping[str, Any] | None) -> Optional[float]:
    if not row:
        return None
    for field in ("current_bid_numeric", "current_bid", "price"):
        parsed = _parse_currency(row.get(field))
        if parsed is not None:
            return parsed
    return None


def _cached_result_needs_refresh(existing: Mapping[str, Any]) -> bool:
    """Return True when a cached row predates current valuation display fields."""
    required_display_fields = [
        "expected_auction_price",
        "expected_auction_bid_basis",
        "expected_auction_source",
        "expected_auction_profit",
        "action_label",
        "current_profit_label",
        "discount_used",
        "economic_max_bid",
        "economic_profit_at_current_bid",
        "economic_profit_at_current_bid_worst",
        "bid_status",
    ]
    return any(_is_missing_value(existing.get(field)) for field in required_display_fields)


VALUATION_INPUT_FIELDS = (
    "url",
    "price",
    "bids",
    "time_remaining_or_date_sold",
    "general_condition",
    "odometer_reading",
    "year",
    "make",
    "model",
    "variant",
    "body_type",
    "transmission",
    "fuel_type",
    "location",
    "rego_expiry",
    "rego_state",
    "canonical_tag",
    "canonical_reason",
    "service_history",
    "key",
    "spare_key",
    "owners_manual",
    "engine_turns_over",
)


def _hashable_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float, bool)):
        return value
    return str(value).strip()


@lru_cache(maxsize=1)
def _repair_rules_signature() -> str:
    payload: dict[str, Any] = {
        "repair_pricing_py": None,
        "condition_dictionary_v2": None,
        "repair_review_decisions": None,
    }
    for key, path in (
        ("repair_pricing_py", Path(__file__).resolve().parent.parent / "shared" / "repair_pricing.py"),
        ("condition_dictionary_v2", V2_DICTIONARY_PATH),
        ("repair_review_decisions", DECISIONS_PATH),
    ):
        try:
            payload[key] = sha256(path.read_bytes()).hexdigest()
        except OSError:
            payload[key] = "missing"
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _valuation_input_hash(
    listing_row: Mapping[str, Any],
    *,
    resale_mid: float | None,
    comps_median: float | None,
    comps_count: int | None,
    analysis_context: str | None,
    km_percentile: float | None,
    autotrader_median: float | None,
    carsales_estimate: float | None,
    listings_cluster_ok: bool | None,
    market_lifecycle: Mapping[str, Any] | None = None,
    reauction_context: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "fields": {
            field: _hashable_value(listing_row.get(field))
            for field in VALUATION_INPUT_FIELDS
        },
        "resale_mid": _hashable_value(resale_mid),
        "comps_median": _hashable_value(comps_median),
        "comps_count": _hashable_value(comps_count),
        "analysis_context": _hashable_value(analysis_context),
        "km_percentile": _hashable_value(km_percentile),
        "autotrader_median": _hashable_value(autotrader_median),
        "carsales_estimate": _hashable_value(carsales_estimate),
        "listings_cluster_ok": _hashable_value(listings_cluster_ok),
        "market_lifecycle": {
            key: _hashable_value(value)
            for key, value in (market_lifecycle or {}).items()
        },
        "reauction_context": {
            key: _hashable_value(value)
            for key, value in (reauction_context or {}).items()
        },
        "repair_rules_signature": _repair_rules_signature(),
        "valuation_policy_version": "unresolved_repairs_review_v1",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _with_price_change_metadata(
    row: Dict[str, Any],
    existing_row: Mapping[str, Any] | None,
    *,
    changed_at: str | None = None,
) -> Dict[str, Any]:
    enriched = dict(row)
    new_bid = _current_bid_value(enriched)
    old_bid = _current_bid_value(existing_row)

    if new_bid is not None and _is_missing_value(enriched.get("current_bid_numeric")):
        enriched["current_bid_numeric"] = new_bid

    if old_bid is None or new_bid is None:
        return enriched

    delta = float(new_bid) - float(old_bid)
    if abs(delta) > 0.01:
        enriched["previous_current_bid"] = existing_row.get("current_bid") or _format_currency(old_bid)
        enriched["previous_current_bid_numeric"] = old_bid
        enriched["price_change_delta"] = delta
        enriched["price_change_direction"] = "increased" if delta > 0 else "decreased"
        enriched["price_changed_at"] = changed_at or datetime.now(tz=timezone.utc).isoformat()
        return enriched

    for column in (
        "previous_current_bid",
        "previous_current_bid_numeric",
        "price_change_delta",
        "price_change_direction",
        "price_changed_at",
    ):
        if _is_missing_value(enriched.get(column)):
            enriched[column] = existing_row.get(column)
    return enriched


def _risk_flags_set(row: Mapping[str, Any] | None) -> set[str]:
    if not row:
        return set()
    raw = str(row.get("risk_flags") or "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split("|") if part.strip()}


def _coverage_status(row: Mapping[str, Any] | None) -> str:
    if not row:
        return "missing"
    verdict = str(row.get("computed_verdict") or row.get("verdict") or "").strip().lower()
    flags = _risk_flags_set(row)
    if verdict in {"not covered", "not eligible"}:
        return "not_covered"
    if {"NO_CURVE", "KM_OUT_OF_RANGE"} & flags:
        return "not_covered"
    return "covered"


def _action_rank(value: Any) -> int:
    text = str(value or "").strip().lower()
    ranks = {
        "buy": 3,
        "bid carefully": 3,
        "watch": 2,
        "watch closely": 2,
        "review": 2,
        "avoid": 1,
        "ignore": 1,
    }
    return ranks.get(text, 0)


def _verdict_rank(value: Any) -> int:
    text = str(value or "").strip().lower()
    ranks = {
        "strong flip": 5,
        "conditional flip": 4,
        "good": 4,
        "marginal (repairs)": 3,
        "not viable": 2,
        "trap": 2,
        "avoid": 1,
        "not covered": 0,
        "not eligible": 0,
    }
    return ranks.get(text, 0)


def _change_direction(
    existing_row: Mapping[str, Any] | None,
    row: Mapping[str, Any],
    event_types: list[str],
) -> str:
    improved = False
    worsened = False

    if "verdict_changed" in event_types:
        old_rank = _verdict_rank(existing_row.get("computed_verdict") if existing_row else None)
        new_rank = _verdict_rank(row.get("computed_verdict"))
        improved |= new_rank > old_rank
        worsened |= new_rank < old_rank
    if "action_changed" in event_types:
        old_rank = _action_rank(existing_row.get("action_label") if existing_row else None)
        new_rank = _action_rank(row.get("action_label"))
        improved |= new_rank > old_rank
        worsened |= new_rank < old_rank

    old_max_bid = _parse_currency(existing_row.get("recommended_max_bid")) if existing_row else None
    new_max_bid = _parse_currency(row.get("recommended_max_bid"))
    if "max_bid_changed" in event_types and old_max_bid is not None and new_max_bid is not None:
        improved |= new_max_bid > old_max_bid
        worsened |= new_max_bid < old_max_bid

    old_repair = _parse_currency(existing_row.get("repair_estimate")) if existing_row else None
    new_repair = _parse_currency(row.get("repair_estimate"))
    if "repair_changed" in event_types and old_repair is not None and new_repair is not None:
        improved |= new_repair < old_repair
        worsened |= new_repair > old_repair

    if "coverage_changed" in event_types:
        old_cov = _coverage_status(existing_row)
        new_cov = _coverage_status(row)
        improved |= old_cov != "covered" and new_cov == "covered"
        worsened |= old_cov == "covered" and new_cov != "covered"

    if "risk_flags_changed" in event_types:
        old_flags = _risk_flags_set(existing_row)
        new_flags = _risk_flags_set(row)
        improved |= bool(old_flags - new_flags)
        worsened |= bool(new_flags - old_flags)

    if improved and not worsened:
        return "improved"
    if worsened and not improved:
        return "worsened"
    return "neutral"


def _format_event_delta(value: float) -> str:
    return _format_currency(abs(value)) or "$0"


def _decision_event_payload(
    row: Mapping[str, Any],
    existing_row: Mapping[str, Any] | None,
) -> Dict[str, Any] | None:
    if not existing_row:
        return None

    event_types: list[str] = []
    reasons: list[str] = []

    previous_verdict = str(existing_row.get("computed_verdict") or existing_row.get("verdict") or "").strip()
    new_verdict = str(row.get("computed_verdict") or row.get("verdict") or "").strip()
    if previous_verdict != new_verdict:
        event_types.append("verdict_changed")
        reasons.append(f"Verdict changed from {previous_verdict or 'unknown'} to {new_verdict or 'unknown'}")

    previous_action = str(existing_row.get("action_label") or "").strip()
    new_action = str(row.get("action_label") or "").strip()
    if previous_action != new_action:
        event_types.append("action_changed")
        reasons.append(f"Action changed from {previous_action or 'unknown'} to {new_action or 'unknown'}")

    previous_max_bid = _parse_currency(existing_row.get("recommended_max_bid"))
    new_max_bid = _parse_currency(row.get("recommended_max_bid"))
    if (
        previous_max_bid is not None
        and new_max_bid is not None
        and abs(new_max_bid - previous_max_bid) >= DECISION_EVENT_MAX_BID_THRESHOLD
    ):
        event_types.append("max_bid_changed")
        direction = "increased" if new_max_bid > previous_max_bid else "decreased"
        reasons.append(
            f"Safe max bid {direction} by {_format_event_delta(new_max_bid - previous_max_bid)}"
        )

    previous_repair = _parse_currency(existing_row.get("repair_estimate"))
    new_repair = _parse_currency(row.get("repair_estimate"))
    if (
        previous_repair is not None
        and new_repair is not None
        and abs(new_repair - previous_repair) >= DECISION_EVENT_REPAIR_THRESHOLD
    ):
        event_types.append("repair_changed")
        direction = "increased" if new_repair > previous_repair else "decreased"
        reasons.append(
            f"Repair estimate {direction} by {_format_event_delta(new_repair - previous_repair)}"
        )

    previous_risk_flags = _risk_flags_set(existing_row)
    new_risk_flags = _risk_flags_set(row)
    if previous_risk_flags != new_risk_flags:
        event_types.append("risk_flags_changed")
        added_flags = sorted(new_risk_flags - previous_risk_flags)
        removed_flags = sorted(previous_risk_flags - new_risk_flags)
        flag_notes: list[str] = []
        if added_flags:
            flag_notes.append(f"added {', '.join(added_flags)}")
        if removed_flags:
            flag_notes.append(f"removed {', '.join(removed_flags)}")
        reasons.append("Risk flags changed: " + "; ".join(flag_notes))

    previous_coverage_status = _coverage_status(existing_row)
    new_coverage_status = _coverage_status(row)
    if previous_coverage_status != new_coverage_status:
        event_types.append("coverage_changed")
        reasons.append(
            f"Coverage changed from {previous_coverage_status.replace('_', ' ')} to {new_coverage_status.replace('_', ' ')}"
        )

    previous_bid_status = str(existing_row.get("bid_status") or "").strip()
    new_bid_status = str(row.get("bid_status") or "").strip()
    previous_current_bid = _current_bid_value(existing_row)
    new_current_bid = _current_bid_value(row)
    if (
        previous_bid_status != new_bid_status
        and previous_current_bid is not None
        and new_current_bid is not None
        and abs(new_current_bid - previous_current_bid) >= DECISION_EVENT_CURRENT_BID_THRESHOLD
    ):
        event_types.append("bid_status_changed")
        reasons.append(
            f"Current bid moved listing from {previous_bid_status or 'unknown'} to {new_bid_status or 'unknown'}"
        )

    if not event_types:
        return None

    return {
        "event_at": str(row.get("analysis_timestamp") or datetime.now(tz=timezone.utc).isoformat()),
        "url": str(row.get("url") or existing_row.get("url") or "").strip(),
        "year": row.get("year") or existing_row.get("year"),
        "make": row.get("make") or existing_row.get("make"),
        "model": row.get("model") or existing_row.get("model"),
        "variant": row.get("variant") or existing_row.get("variant"),
        "location": row.get("location") or existing_row.get("location"),
        "event_types": "|".join(event_types),
        "direction": _change_direction(existing_row, row, event_types),
        "previous_verdict": previous_verdict,
        "new_verdict": new_verdict,
        "previous_action": previous_action,
        "new_action": new_action,
        "previous_max_bid": existing_row.get("recommended_max_bid"),
        "new_max_bid": row.get("recommended_max_bid"),
        "previous_current_bid": existing_row.get("current_bid"),
        "new_current_bid": row.get("current_bid"),
        "previous_bid_status": previous_bid_status,
        "new_bid_status": new_bid_status,
        "previous_repair_estimate": existing_row.get("repair_estimate"),
        "new_repair_estimate": row.get("repair_estimate"),
        "previous_risk_flags": "|".join(sorted(previous_risk_flags)),
        "new_risk_flags": "|".join(sorted(new_risk_flags)),
        "previous_coverage_status": previous_coverage_status,
        "new_coverage_status": new_coverage_status,
        "change_reason_summary": " | ".join(reasons),
    }


def _append_decision_event(row: Mapping[str, Any], existing_row: Mapping[str, Any] | None) -> None:
    event = _decision_event_payload(row, existing_row)
    if not event:
        return
    append_dict_rows_csv_atomic(DECISION_EVENTS_PATH, DECISION_EVENT_COLUMNS, [event])


def _save_result_row(row: Dict[str, Any]) -> None:
    df = load_cached_results()
    existing_row: Dict[str, Any] | None = None
    url = row.get("url")
    if url and "url" in df.columns:
        existing_matches = df[df["url"] == url]
        if not existing_matches.empty:
            existing_row = existing_matches.iloc[-1].to_dict()
    row = _with_price_change_metadata(row, existing_row)
    new_row = pd.DataFrame([row])
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="The behavior of DataFrame concatenation with empty or all-NA entries is deprecated",
            category=FutureWarning,
        )
        combined = pd.concat([df, new_row], ignore_index=True)
    combined = combined.drop_duplicates(subset=["url"], keep="last")
    write_dataframe_csv_atomic(combined, AI_RESULTS_PATH, index=False)
    _append_decision_event(row, existing_row)
    _maybe_send_listing_alerts(row, existing_row)


def upsert_manual_result_row(row: Dict[str, Any]) -> None:
    """Persist a synthesized valuation row through the normal alert/state path."""
    payload = {column: row.get(column) for column in REQUIRED_COLUMNS}
    _save_result_row(payload)


def _is_good_verdict(verdict: Any) -> bool:
    verdict_text = str(verdict or "").strip().lower()
    return "strong" in verdict_text or verdict_text == "good"


def _ai_analysis_action(row: Mapping[str, Any] | None) -> str:
    if not row:
        return ""
    fallback = str(row.get("action_label") or "").strip()
    return derive_action_label_from_row(
        row,
        min_profit=MIN_NET_PROFIT_ABSOLUTE,
        fallback=fallback,
    )


def _dataset_contains_url(path: Path, url: str) -> bool:
    if not path.exists() or not url:
        return False
    try:
        df = pd.read_csv(path, usecols=["url"], low_memory=False)
    except Exception:
        return False
    if df.empty or "url" not in df.columns:
        return False
    return bool(df["url"].dropna().astype(str).str.strip().eq(url).any())


def _is_current_active_listing(row: Mapping[str, Any]) -> bool:
    url = str(row.get("url") or "").strip()
    if not url:
        return False
    if not _dataset_contains_url(ACTIVE_LISTINGS_PATH, url):
        return False
    if _dataset_contains_url(SOLD_LISTINGS_PATH, url):
        return False
    if _dataset_contains_url(REFERRED_LISTINGS_PATH, url):
        return False
    return True


def _alert_title(row: Mapping[str, Any]) -> str:
    parts = [
        str(row.get("year") or "").strip(),
        str(row.get("make") or "").strip(),
        str(row.get("model") or "").strip(),
        str(row.get("variant") or "").strip(),
    ]
    title = " ".join(part for part in parts if part)
    return title or "Listing"


def _autosniper_listing_url(listing_url: str) -> str:
    page_url = str(os.getenv("AUTOSNIPER_AI_ANALYSIS_URL") or "").strip()
    if not page_url:
        app_url = str(os.getenv("AUTOSNIPER_APP_URL") or DEFAULT_AUTOSNIPER_APP_URL).strip().rstrip("/")
        page_url = f"{app_url}/AI_ANALYSIS"
    separator = "&" if "?" in page_url else "?"
    return f"{page_url}{separator}{urlencode({'listing_url': listing_url})}"


def _ai_analysis_alert_message(row: Mapping[str, Any], *, title: str, url: str) -> str:
    action_label = _ai_analysis_action(row) or "N/A"
    bid_status = str(row.get("bid_status") or "N/A").strip() or "N/A"
    return (
        "$$$ POTENTIAL BUY ALERT $$$\n"
        "Alert type: AI Analysis Buy candidate\n"
        f"Vehicle: {title}\n"
        "Why sent: this current active listing is marked Buy in AI Analysis.\n"
        "\n"
        "DEAL NUMBERS\n"
        f"Current bid: {row.get('current_bid') or row.get('price') or 'N/A'}\n"
        f"Proxy max bid: {row.get('recommended_max_bid') or 'N/A'}\n"
        f"Profit now: {row.get('economic_profit_at_current_bid') or 'N/A'}\n"
        f"Expected auction profit: {row.get('expected_auction_profit') or 'N/A'}\n"
        "\n"
        "STATUS\n"
        f"Action: {action_label}\n"
        f"Verdict: {row.get('computed_verdict') or row.get('verdict') or 'N/A'}\n"
        f"Bid position: {bid_status}\n"
        f"Analysed: {row.get('analysis_timestamp') or 'N/A'}\n"
        "\n"
        "LINKS\n"
        f"AutoSniper page: {_autosniper_listing_url(url)}\n"
        f"Auction page: {url}"
    )


def _unresolved_repairs_alert_message(row: Mapping[str, Any], *, title: str, url: str) -> str:
    unresolved = str(row.get("unresolved_repairs") or "Unclassified condition item").strip()
    return (
        "$$$ POTENTIAL BUY - UNRESOLVED REPAIRS $$$\n"
        "Alert type: Potential buy requiring Repair Review\n"
        f"Vehicle: {title}\n"
        "Why sent: the deal numbers may qualify, but unresolved repairs prevent a Buy action.\n"
        "\n"
        "REPAIR REVIEW REQUIRED\n"
        f"Unresolved repairs: {unresolved}\n"
        "Action: Review - do not bid until these repairs are classified and repriced.\n"
        "\n"
        "DEAL NUMBERS\n"
        f"Current bid: {row.get('current_bid') or row.get('price') or 'N/A'}\n"
        f"Proxy max bid: {row.get('recommended_max_bid') or 'N/A'}\n"
        f"Current priced repairs: {row.get('repair_estimate') or 'N/A'}\n"
        "\n"
        "STATUS\n"
        f"Verdict: {row.get('computed_verdict') or row.get('verdict') or 'N/A'}\n"
        f"Bid position: {row.get('bid_status') or 'N/A'}\n"
        f"Analysed: {row.get('analysis_timestamp') or 'N/A'}\n"
        "\n"
        "LINKS\n"
        f"AutoSniper page: {_autosniper_listing_url(url)}\n"
        f"Auction page: {url}"
    )


def _maybe_send_listing_alerts(
    row: Mapping[str, Any],
    existing_row: Mapping[str, Any] | None,
) -> None:
    if str(row.get("analysis_context") or "").strip().lower() != "active":
        return
    if not _is_current_active_listing(row):
        return

    title = _alert_title(row)
    url = str(row.get("url") or "").strip()
    if not url:
        return

    current_action = _ai_analysis_action(row)
    previous_action = _ai_analysis_action(existing_row)
    alert_scope = "listing_bid_ready"
    previous_alert_state = get_alert_state(alert_scope, url)
    unresolved_candidate = _parse_yes_no(row.get("potential_buy_unresolved_repairs")) is True
    if unresolved_candidate:
        state_value = "ai_analysis_buy_unresolved_repairs"
        message = _unresolved_repairs_alert_message(row, title=title, url=url)
    elif current_action == "Buy":
        state_value = "ai_analysis_buy"
        message = _ai_analysis_alert_message(row, title=title, url=url)
    elif previous_action == "Buy" or previous_alert_state in {
        "ai_analysis_buy",
        "ai_analysis_buy_unresolved_repairs",
    }:
        state_value = "ai_analysis_not_buy"
        message = (
            "BUY ALERT UPDATE - NO LONGER A BUY\n"
            "Alert type: Buy status changed\n"
            f"Vehicle: {title}\n"
            "Why sent: this listing was previously alerted as Buy, but AI Analysis changed.\n"
            "\n"
            "STATUS\n"
            f"Previous action: {previous_action or 'N/A'}\n"
            f"Current action: {current_action or 'N/A'}\n"
            f"Verdict: {row.get('computed_verdict') or row.get('verdict') or 'N/A'}\n"
            f"Bid position: {row.get('bid_status') or 'N/A'}\n"
            "\n"
            "DEAL NUMBERS\n"
            f"Current bid: {row.get('current_bid') or row.get('price') or 'N/A'}\n"
            f"Proxy max bid: {row.get('recommended_max_bid') or 'N/A'}\n"
            f"Analysed: {row.get('analysis_timestamp') or 'N/A'}\n"
            "\n"
            "LINKS\n"
            f"AutoSniper page: {_autosniper_listing_url(url)}\n"
            f"Auction page: {url}"
        )
    else:
        return

    try:
        send_on_state_change(
            alert_scope,
            url,
            state_value,
            message,
            verdict=str(row.get("computed_verdict") or ""),
        )
    except Exception as exc:
        print(f"WARNING: Telegram alert send failed for {url}: {type(exc).__name__}: {exc}")
        return


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


def _profit_margin_percent_text(
    profit_value: Optional[float],
    resale_value: Optional[float],
) -> Optional[str]:
    if profit_value is None or resale_value is None or resale_value <= 0:
        return None
    return f"{(profit_value / resale_value) * 100:.1f}%"


def _profit_margin_percent_value(
    profit_value: Optional[float],
    resale_value: Optional[float],
) -> Optional[float]:
    if profit_value is None or resale_value is None or resale_value <= 0:
        return None
    return (profit_value / resale_value) * 100.0


def _market_curve_delta(market_median: Any, curve_estimate: Any) -> Optional[float]:
    market_value = _parse_currency(market_median)
    curve_value = _parse_currency(curve_estimate)
    if market_value is None or curve_value is None or curve_value <= 0:
        return None
    return (market_value - curve_value) / curve_value


def _apply_market_lifecycle_confidence(
    confidence: float,
    risk_flags: list[str],
    notes: list[str],
    market_lifecycle: Mapping[str, Any] | None,
) -> tuple[float, list[str], list[str]]:
    if not market_lifecycle:
        return confidence, risk_flags, notes

    fast_clears = _parse_int(market_lifecycle.get("fast_clear_count")) or 0
    stale_active = _parse_int(market_lifecycle.get("stale_active_count")) or 0

    if fast_clears >= FAST_MARKET_CLEAR_MIN_COUNT:
        confidence += FAST_MARKET_CLEAR_CONFIDENCE_BOOST
        notes.append(
            "Retail liquidity signal: "
            f"{fast_clears} matched listing(s) disappeared within {FAST_MARKET_CLEAR_DAYS} days near the curve price."
        )

    if stale_active >= STALE_MARKET_MIN_COUNT:
        confidence -= STALE_MARKET_CONFIDENCE_PENALTY
        if STALE_MARKET_FLAG not in risk_flags:
            risk_flags.append(STALE_MARKET_FLAG)
        notes.append(
            "Retail liquidity warning: "
            f"{stale_active} matched active listing(s) have sat for {STALE_MARKET_DAYS}+ days near the curve price."
        )

    return max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, confidence)), risk_flags, notes


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


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _parse_seat_count(value: Any) -> Optional[int]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    match = re.search(r"\d+", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _parse_yes_no(value: Any) -> Optional[bool]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"yes", "y", "true", "present", "full", "complete"}:
        return True
    if text in {"no", "n", "false", "missing", "none", "absent"}:
        return False
    if "yes" in text:
        return True
    if "no" in text:
        return False
    return None


def _estimate_detailing_cost(listing: Mapping[str, Any]) -> float:
    body_text = " ".join(
        str(listing.get(field) or "")
        for field in ("body_type", "variant", "model")
    ).lower()
    seats = _parse_seat_count(listing.get("no_of_seats"))
    if seats is not None and seats >= 7:
        return DETAILING_LARGE_SUV_4WD
    if any(keyword in body_text for keyword in ("7 seat", "7seater", "7 seater")):
        return DETAILING_LARGE_SUV_4WD
    if any(
        keyword in body_text
        for keyword in (
            "4wd",
            "4x4",
            "dual cab",
            "cab chassis",
            "cab-chassis",
            "cabchassis",
            "ute",
            "pickup",
            "pick-up",
            "pick up",
        )
    ):
        return DETAILING_LARGE_SUV_4WD
    if any(keyword in body_text for keyword in ("suv", "wagon")):
        return DETAILING_SMALL_SUV_WAGON
    if any(keyword in body_text for keyword in ("hatch", "hatchback", "sedan", "saloon", "coupe", "convertible")):
        return DETAILING_HATCH_SEDAN
    return DETAILING_SMALL_SUV_WAGON


def _is_unregistered(listing: Mapping[str, Any]) -> bool:
    expiry = str(listing.get("rego_expiry") or "").lower()
    rego_no = str(listing.get("rego_no") or "").strip().lower()
    if "unregistered" in expiry or "without plates" in expiry:
        return True
    if not expiry and (not rego_no or "no plates" in rego_no):
        return True
    return False


def _estimate_transport_cost(location: Any) -> float:
    """State-aware transport estimate into the operating state.

    Local/in-state (or unparseable) locations keep the flat DEFAULT_TRANSPORT.
    Interstate locations use the conservative depot-to-depot lane table so
    interstate listings carry honest logistics costs instead of local pricing.
    """
    state = _state_from_text(location)
    if state is None or state == OPERATING_STATE:
        return DEFAULT_TRANSPORT
    return INTERSTATE_TRANSPORT_COSTS.get(state, INTERSTATE_TRANSPORT_DEFAULT)


def _state_from_text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = re.sub(r"[^A-Z]", " ", str(value).upper())
    tokens = {token for token in text.split() if token}
    for state in ("NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"):
        if state in tokens:
            return state
    return None


def _listing_location_state(listing: Mapping[str, Any]) -> str | None:
    for field in (
        "location_state",
        "state",
        "yard_state",
        "auction_state",
        "location",
        "yard",
        "rego_state",
    ):
        state = _state_from_text(listing.get(field))
        if state:
            return state
    return None


def _is_interstate_listing(listing: Mapping[str, Any]) -> bool:
    state = _listing_location_state(listing)
    return bool(state and state != OPERATING_STATE)


def _interstate_purchase_blocked(listing: Mapping[str, Any]) -> bool:
    """True when the listing is interstate and buying from its state is not enabled."""
    state = _listing_location_state(listing)
    if not state or state == OPERATING_STATE:
        return False
    if not INTERSTATE_BUYING_ALLOWED:
        return True
    if INTERSTATE_ALLOWED_STATES is not None and state not in INTERSTATE_ALLOWED_STATES:
        return True
    return False


def _is_grays_listing(listing: Mapping[str, Any]) -> bool:
    url = str(listing.get("url") or "").lower()
    source = str(listing.get("source") or listing.get("platform") or "").lower()
    return "grays" in url or "grays" in source


def _grays_buyer_premium(final_bid: float) -> float:
    if final_bid <= 2000:
        return 495.0
    if final_bid <= 5000:
        return 650.0
    if final_bid <= 10000:
        return 710.0
    if final_bid <= 30000:
        return final_bid * 0.07
    if final_bid <= 40000:
        return final_bid * 0.06
    return final_bid * 0.05


def _estimate_bid_cost_components(purchase_price: float, listing: Mapping[str, Any]) -> dict[str, float]:
    if _is_grays_listing(listing):
        auction_fee = _grays_buyer_premium(purchase_price)
    else:
        auction_fee = max(MIN_FEES, purchase_price * FEES_RATE)
    transport_cost = _estimate_transport_cost(listing.get("location"))
    rego_cost = REGISTERED_REGO_COST
    roadworthy_cost = ROADWORTHY_ESTIMATE if _is_unregistered(listing) else 0.0
    detail_cost = _estimate_detailing_cost(listing)
    prep_cost = DEFAULT_PREP + detail_cost
    return {
        "auction_fee": auction_fee,
        "transport_cost": transport_cost,
        "detail_cost": detail_cost,
        "rego_cost": rego_cost,
        "roadworthy_cost": roadworthy_cost,
        "prep_cost": prep_cost,
    }


def _estimate_costs(purchase_price: float, listing: Mapping[str, Any]) -> dict[str, float]:
    components = _estimate_bid_cost_components(purchase_price, listing)
    return {
        "fees_estimate": components["auction_fee"],
        "transport_estimate": components["transport_cost"],
        "rego_estimate": components["rego_cost"],
        "roadworthy_estimate": components["roadworthy_cost"],
        "prep_estimate": components["prep_cost"],
    }


def _expected_auction_estimate(
    resale_value: Optional[float],
    *,
    comps_median: Any = None,
    comps_count: int | None = None,
    model_prediction: dict | None = None,
) -> tuple[Optional[float], str | None, int | None]:
    comp_count = _parse_int(comps_count)
    comp_median = _parse_currency(comps_median)

    # CatBoost model prediction — use when available and comps baseline exists
    if (
        model_prediction is not None
        and comp_median is not None
        and comp_median > 0
        and comp_count is not None
        and comp_count >= MIN_EXPECTED_AUCTION_COMPS
    ):
        q50_price = model_prediction.get("q50_price")
        if q50_price is not None and q50_price > 0:
            return _round_to_10(float(q50_price)), "catboost_model", comp_count

    # Fall back to raw comps median when count is sufficient
    if (
        comp_median is not None
        and comp_median > 0
        and comp_count is not None
        and comp_count >= MIN_EXPECTED_AUCTION_COMPS
    ):
        return _round_to_10(comp_median), "historical_sold_median", comp_count

    # Last resort: resale * discount
    if resale_value is None or resale_value <= 0:
        return None, None, comp_count
    return _round_to_10(resale_value * DEFAULT_DISCOUNT), "resale_discount", comp_count


def _expected_auction_price(
    resale_value: Optional[float],
    *,
    comps_median: Any = None,
    comps_count: int | None = None,
) -> Optional[float]:
    estimate, _, _ = _expected_auction_estimate(
        resale_value,
        comps_median=comps_median,
        comps_count=comps_count,
    )
    return estimate


def _discounted_resale_cap_price(resale_value: Optional[float]) -> Optional[float]:
    if resale_value is None or resale_value <= 0:
        return None
    return _round_to_10(resale_value * DEFAULT_DISCOUNT)


def _profit_at_purchase_price(
    resale_mid: Optional[float],
    resale_low: Optional[float],
    purchase_price: Optional[float],
    listing: Mapping[str, Any],
    repair_cost: float,
) -> tuple[Optional[float], Optional[float]]:
    if purchase_price is None:
        return None, None
    mid_profit = None
    worst_profit = None
    if resale_mid is not None:
        mid_profit = _net_profit_value(resale_mid, purchase_price, listing) - repair_cost
    if resale_low is not None:
        worst_profit = _net_profit_value(resale_low, purchase_price, listing) - repair_cost
    return mid_profit, worst_profit


def _profit_score(profit_worst: Optional[float], resale_mid: Optional[float]) -> Optional[float]:
    if profit_worst is None or resale_mid is None or resale_mid <= 0:
        return None
    if profit_worst <= 0:
        return 0.0
    target_score = (profit_worst / MIN_NET_PROFIT_ABSOLUTE) * 35.0
    margin_score = (profit_worst / resale_mid) * 100.0
    return round(max(0.0, min(100.0, target_score + margin_score)), 1)


def _profit_label(profit_worst: Optional[float], resale_mid: Optional[float]) -> str:
    score = _profit_score(profit_worst, resale_mid)
    if score is None:
        return "Unknown"
    if score >= 80:
        return "Strong"
    if score >= 60:
        return "Good"
    if score >= 40:
        return "Conditional"
    if score > 0:
        return "Thin"
    return "No edge"


def _hard_max_safety_label(net_profit_worst: Optional[float]) -> str:
    if net_profit_worst is None:
        return "Unknown"
    if net_profit_worst >= 3_000:
        return "Strong"
    if net_profit_worst >= MIN_NET_PROFIT_ABSOLUTE:
        return "Conditional"
    if net_profit_worst > 0:
        return "Thin"
    return "No edge"


def _flip_difficulty(
    listing: Mapping[str, Any],
    repair_assessment: Any,
    risk_flags: list[str],
) -> tuple[str, str]:
    reasons: list[str] = []
    points = 0
    risk_set = set(risk_flags)
    if "INTERSTATE" in risk_set:
        return "Out of scope", "Interstate listing"
    if repair_assessment.hard_avoid or "MECHANICAL" in risk_set:
        return "Hard", "Mechanical/hard-avoid risk"

    if "WARNING_LIGHT" in risk_set or "ENGINE_UNKNOWN" in risk_set:
        points += 3
        reasons.append("warning/mechanical uncertainty")
    if "UNREGISTERED" in risk_set:
        points += 2
        reasons.append("unregistered")
    if "HIGH_KM" in risk_set:
        points += 2
        reasons.append("high kilometres")
    if "NO_SERVICE_HISTORY" in risk_set:
        points += 2
        reasons.append("no service history")
    elif str(listing.get("service_history") or "").strip().lower() == "partial":
        points += 1
        reasons.append("partial service history")
    if "MISSING_KEYS" in risk_set:
        points += 1
        reasons.append("missing spare key")
    cosmetic_panels = int(getattr(repair_assessment, "cosmetic_panels", 0) or 0)
    if cosmetic_panels:
        points += min(2, cosmetic_panels)
        reasons.append("cosmetic repairs")

    if points >= 5:
        return "Hard", "; ".join(reasons)
    if points >= 2:
        return "Medium", "; ".join(reasons)
    if points == 1:
        return "Easy-medium", "; ".join(reasons)
    return "Easy", "Clean basic flip checks"


def _bid_status_label(
    current_bid: Optional[float],
    expected_auction_price: Optional[float],
    hard_max_bid: Optional[float],
) -> str:
    if current_bid is None:
        return "Unknown"
    if hard_max_bid is not None:
        if hard_max_bid <= 0 or current_bid > hard_max_bid + EDGE_BUFFER:
            return "Over max"
        if current_bid >= hard_max_bid * 0.95:
            return "At ceiling"
        if current_bid >= hard_max_bid * 0.85:
            return "Near ceiling"
    if expected_auction_price is not None and expected_auction_price > 0:
        if current_bid <= expected_auction_price * 0.80:
            return "Cheap"
        if current_bid <= expected_auction_price:
            return "Below expected"
        return "Above expected"
    return "Open"


def _action_label(
    computed_verdict: str,
    bid_status: str,
    expected_auction_worst_profit: Optional[float],
    current_worst_profit: Optional[float],
    hard_max_safety: str,
    comps_count: int | None = None,
) -> str:
    return derive_action_label(
        DecisionPolicyInput(
            computed_verdict=computed_verdict,
            bid_status=bid_status,
            expected_auction_worst_profit=expected_auction_worst_profit,
            current_worst_profit=current_worst_profit,
            hard_max_safety=hard_max_safety,
            min_profit=MIN_NET_PROFIT_ABSOLUTE,
            comps_count=comps_count,
        )
    )


def _discounted_bid_cap(
    expected_auction_price: Optional[float],
    *,
    repair_cost: float = 0.0,
    margin: float,
) -> Optional[float]:
    if expected_auction_price is None:
        return None
    return max(0.0, expected_auction_price - max(0.0, float(repair_cost)) - max(0.0, float(margin)))


def _detect_risk_flags(listing: Mapping[str, Any]) -> list[str]:
    flags: list[str] = []
    if _interstate_purchase_blocked(listing):
        flags.append("INTERSTATE")
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


def _calculate_curve_coverage_score(
    resale_mid: float | None,
    *,
    km_percentile: float | None = None,
) -> float:
    if resale_mid is None or resale_mid <= 0:
        return 0.0
    score = 0.85
    if km_percentile is not None:
        score += 0.15
    return max(0.0, min(1.0, score))


def _calculate_repair_certainty_score(
    listing: Mapping[str, Any],
    repair_assessment: Any,
) -> float:
    general_condition = str(listing.get("general_condition") or "").strip()
    if not general_condition:
        return 0.35

    score = 0.70
    if getattr(repair_assessment, "reasons", None):
        score += 0.12
    if getattr(repair_assessment, "severity_level", ""):
        score += 0.08
    if getattr(repair_assessment, "pills", None):
        score += 0.05
    if "UNKNOWN" in set(getattr(repair_assessment, "pills", []) or []):
        score -= 0.25
    if getattr(repair_assessment, "risk_buffer", 0) > 0:
        score -= 0.10
    if any(
        str(getattr(fragment, "status", "")).strip().lower() == "unclassified"
        for fragment in (getattr(repair_assessment, "fragments", None) or [])
    ):
        score = min(score, 0.50)
    return max(0.0, min(1.0, score))


def _calculate_data_completeness_score(listing: Mapping[str, Any]) -> float:
    checks = [
        _has_value(listing.get("year")),
        _has_value(listing.get("make")),
        _has_value(listing.get("model")),
        _has_value(listing.get("variant")),
        _has_value(listing.get("location")),
        _parse_currency(listing.get("price")) is not None,
        _parse_odometer(listing.get("odometer_numeric") or listing.get("odometer_reading")) is not None,
        _has_value(listing.get("transmission")),
        _has_value(listing.get("general_condition")),
        _has_value(listing.get("service_history")),
        _has_value(listing.get("owners_manual")),
        _has_value(listing.get("key")),
        _has_value(listing.get("spare_key")),
        (_parse_int(listing.get("historical_match_count")) or 0) > 0,
    ]
    total_checks = len(checks)
    if total_checks == 0:
        return 0.0
    return sum(1 for passed in checks if passed) / total_checks


def _calculate_confidence(
    listing: Mapping[str, Any],
    risk_flags: list[str],
    *,
    resale_mid: float | None = None,
    repair_assessment: Any = None,
    km_percentile: float | None = None,
) -> float | tuple[float, list[str]]:
    # Backward-compatible mode for existing UI callers that still expect the old
    # float-only confidence result.
    if resale_mid is None and repair_assessment is None:
        confidence = 0.8
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

    curve_score = _calculate_curve_coverage_score(resale_mid, km_percentile=km_percentile)
    repair_score = _calculate_repair_certainty_score(listing, repair_assessment)
    data_score = _calculate_data_completeness_score(listing)

    weighted_confidence = (
        (curve_score * CURVE_COVERAGE_WEIGHT)
        + (repair_score * REPAIR_CERTAINTY_WEIGHT)
        + (data_score * DATA_COMPLETENESS_WEIGHT)
    )
    risk_penalty = sum(RISK_CONFIDENCE_PENALTIES.get(flag, 0.04) for flag in risk_flags) * CONFIDENCE_RISK_PENALTY_SCALE
    confidence = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, weighted_confidence - risk_penalty))
    notes = [
        (
            "Confidence factors: "
            f"curve_coverage={curve_score:.2f}, "
            f"repair_certainty={repair_score:.2f}, "
            f"data_completeness={data_score:.2f}, "
            f"risk_penalty={risk_penalty:.2f}"
        )
    ]
    return confidence, notes


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


def run_curve_listing_analysis(
    listing_row: pd.Series,
    resale_mid: float | None,
    *,
    comps_median: float | None = None,
    comps_count: int | None = None,
    analysis_context: str | None = None,
    km_percentile: float | None = None,
    historical_matches: List[Dict[str, Any]] | None = None,
    autotrader_median: float | None = None,
    carsales_estimate: float | None = None,
    listings_cluster_ok: bool | None = None,
    market_lifecycle: Mapping[str, Any] | None = None,
    reauction_context: Mapping[str, Any] | None = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    cached_df = load_cached_results()
    url = listing_row.get("url")
    input_hash = _valuation_input_hash(
        listing_row,
        resale_mid=resale_mid,
        comps_median=comps_median,
        comps_count=comps_count,
        analysis_context=analysis_context,
        km_percentile=km_percentile,
        autotrader_median=autotrader_median,
        carsales_estimate=carsales_estimate,
        listings_cluster_ok=listings_cluster_ok,
        market_lifecycle=market_lifecycle,
        reauction_context=reauction_context,
    )

    if (
        not force_refresh
        and url
        and url in set(cached_df["url"].dropna().tolist())
    ):
        existing = cached_df[cached_df["url"] == url].iloc[0].to_dict()
        if _cached_result_needs_refresh(existing) or existing.get("valuation_input_hash") != input_hash:
            force_refresh = True
        else:
            if analysis_context and not existing.get("analysis_context"):
                existing["analysis_context"] = analysis_context
            repair_assessment = assess_repairs(listing_row.get("general_condition", ""))
            if repair_assessment.hard_avoid:
                existing["recommended_max_bid"] = _format_currency(0)
                existing["computed_verdict"] = "Avoid"
                existing["verdict"] = "Avoid"
                existing["net_profit_mid"] = None
                existing["net_profit_worst"] = None
                existing["expected_profit"] = None
                existing["profit_margin_percent"] = None
                risk_flags = str(existing.get("risk_flags") or "")
                if "MECHANICAL" not in risk_flags:
                    existing["risk_flags"] = "|".join(
                        sorted({flag for flag in (risk_flags.split("|") if risk_flags else []) if flag} | {"MECHANICAL"})
                    )
            existing["cached"] = True
            return existing

    if resale_mid is None or resale_mid <= 0:
        result_row = {
            "url": url,
            "analysis_timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "analysis_context": analysis_context,
            "carsales_price_estimate": None,
            "carsales_price_range": None,
            "recommended_max_bid": _format_currency(0),
            "expected_profit": None,
            "profit_margin_percent": None,
            "score_out_of_10": None,
            "confidence_notes": "Confidence factors: curve_coverage=0.00, repair_certainty=0.00, data_completeness=0.00, risk_penalty=0.00",
            "fees_estimate": None,
            "transport_estimate": None,
            "rego_estimate": None,
            "roadworthy_estimate": None,
            "prep_estimate": None,
            "repair_estimate": None,
            "expected_auction_price": None,
            "expected_auction_bid_basis": None,
            "expected_auction_profit": None,
            "expected_auction_worst_profit": None,
            "expected_auction_source": None,
            "expected_auction_comps_count": None,
            "expected_auction_reauction_adjustment": None,
            "expected_auction_reauction_reason": None,
            "reauction_event_count": None,
            "reauction_last_price": None,
            "reauction_price_delta": None,
            "economic_max_bid": _format_currency(0),
            "economic_profit_mid": None,
            "economic_profit_worst": None,
            "economic_profit_at_current_bid": None,
            "economic_profit_at_current_bid_worst": None,
            "bid_policy_gate": "",
            "discount_used": DEFAULT_DISCOUNT,
            "profit_at_current_bid": None,
            "profit_at_current_bid_worst": None,
            "current_profit_score": None,
            "current_profit_label": "Unknown",
            "expected_auction_profit_label": "Unknown",
            "hard_max_safety": "Unknown",
            "flip_difficulty": "Unknown",
            "difficulty_reasons": "No curve coverage",
            "bid_status": "Unknown",
            "action_label": "Review",
            "resale_low": None,
            "resale_mid": None,
            "resale_high": None,
            "net_profit_mid": None,
            "net_profit_worst": None,
            "confidence": 0.0,
            "risk_flags": "NO_CURVE",
            "computed_verdict": "Not Covered",
            "verdict": "Not Covered",
            "no_edge": False,
            "edge_note": "",
            "no_edge_at_current_bid": False,
            "edge_buffer": EDGE_BUFFER,
            "current_bid": listing_row.get("price"),
            "current_bid_numeric": _parse_currency(listing_row.get("price")),
            "bids_observed": listing_row.get("bids"),
            "time_remaining_observed": listing_row.get("time_remaining_or_date_sold"),
            "valuation_input_hash": input_hash,
            "resale_low_value": None,
            "resale_mid_value": None,
            "resale_high_value": None,
            "recommended_max_bid_value": 0.0,
            "economic_max_bid_value": 0.0,
            "net_profit_mid_value": None,
            "net_profit_worst_value": None,
            "expected_auction_price_value": None,
            "expected_auction_bid_basis_value": None,
            "expected_auction_profit_value": None,
            "expected_auction_worst_profit_value": None,
            "profit_at_current_bid_value": None,
            "profit_at_current_bid_worst_value": None,
            "profit_margin_value": None,
        }
        _save_result_row(result_row)
        result_row["cached"] = False
        return result_row

    listing_data = listing_row.to_dict()
    if comps_count is not None:
        listing_data["historical_match_count"] = comps_count
        listing_data["historical_matches_rows"] = comps_count

    repair_assessment = assess_repairs(listing_row.get("general_condition", ""), vehicle_value=resale_mid)
    unresolved_repair_items = sorted(
        {
            str(getattr(fragment, "original_text", "")).strip().rstrip(".")
            for fragment in (getattr(repair_assessment, "fragments", None) or [])
            if str(getattr(fragment, "status", "")).strip().lower() == "unclassified"
            and str(getattr(fragment, "original_text", "")).strip()
        }
    )
    risk_flags = _detect_risk_flags(listing_data)
    if unresolved_repair_items and "UNRESOLVED_REPAIRS" not in risk_flags:
        risk_flags.append("UNRESOLVED_REPAIRS")

    # CatBoost model prediction — build repair features for the feature vector
    model_prediction: dict | None = None
    comp_median_val = _parse_currency(comps_median)
    curve_tag_val = str(listing_data.get("curve_tag") or listing_data.get("canonical_tag") or "")
    if comp_median_val and comp_median_val > 0 and curve_tag_val:
        try:
            repair_feats = build_repair_features(listing_row.get("general_condition", ""))
            repair_tag_flags = {
                f"tag_{cat}": (1 if cat in repair_feats.tags else 0)
                for cat in REPAIR_CATEGORIES
            }
            model_prediction = predict_auction_price(
                listing_data,
                comps_p50=comp_median_val,
                curve_tag=curve_tag_val,
                repair_tags=serialize_tags(repair_feats.tags),
                repair_severity=float(repair_feats.severity),
                decision_condition_only=repair_feats.decision_label,
                estimated_parts_cost_aud=float(repair_assessment.total_cost or 0),
                repair_tag_flags=repair_tag_flags,
                total_repair_tags=len(repair_feats.tags),
            )
        except Exception as exc:
            print(f"WARNING: auction model prediction failed, falling back to curve-only pricing: {type(exc).__name__}: {exc}")
            model_prediction = None
    downside_pct = _calculate_downside_percent(risk_flags)
    upside_pct = _calculate_upside_percent(risk_flags)
    confidence_val, confidence_notes = _calculate_confidence(
        listing_data,
        risk_flags,
        resale_mid=resale_mid,
        repair_assessment=repair_assessment,
        km_percentile=km_percentile,
    )
    notes: list[str] = list(confidence_notes)
    downside_pct, confidence_val, risk_flags, notes = apply_platform_risk_adjustments(
        listing_data, downside_pct, confidence_val, risk_flags, notes
    )
    confidence_val, risk_flags, notes = _apply_market_lifecycle_confidence(
        confidence_val,
        risk_flags,
        notes,
        market_lifecycle,
    )
    confidence_val = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, confidence_val))

    resale_low_val = resale_mid * (1.0 - downside_pct)
    resale_high_val = resale_mid * (1.0 + upside_pct)

    resale_mid_val = _round_to_10(resale_mid)
    resale_low_val = _round_to_10(resale_low_val)
    resale_high_val = _round_to_10(resale_high_val)
    (
        expected_auction_price_val,
        expected_auction_source,
        expected_auction_comps_count,
    ) = _expected_auction_estimate(
        resale_mid_val,
        comps_median=comps_median,
        comps_count=comps_count,
        model_prediction=model_prediction,
    )
    (
        expected_auction_price_val,
        reauction_adjustment_val,
        reauction_reason,
    ) = adjusted_expected_auction_price(expected_auction_price_val, reauction_context)
    if reauction_reason:
        expected_auction_source = (
            f"{expected_auction_source}+{reauction_reason}"
            if expected_auction_source
            else reauction_reason
        )

    min_net_profit = max(MIN_NET_PROFIT_ABSOLUTE, MIN_NET_PROFIT_RATIO * (resale_low_val or resale_mid))
    recommended_max_bid_val = _solve_max_bid(resale_low_val, min_net_profit, listing_data)
    discounted_bid_cap = _discounted_bid_cap(
        expected_auction_price_val,
        repair_cost=0.0,
        margin=min_net_profit,
    )
    if discounted_bid_cap is not None and recommended_max_bid_val is not None:
        recommended_max_bid_val = min(recommended_max_bid_val, discounted_bid_cap)
    elif discounted_bid_cap is not None:
        recommended_max_bid_val = discounted_bid_cap

    current_price_val = _parse_currency(listing_row.get("price"))
    if (
        expected_auction_price_val is not None
        and current_price_val is not None
        and expected_auction_price_val < current_price_val
    ):
        print(f"[WARN] Auction already above expected price: {url}")
    if (
        current_price_val is not None
        and recommended_max_bid_val is not None
        and recommended_max_bid_val < current_price_val
    ):
        pass

    repair_verdict = None
    if repair_assessment.hard_avoid:
        hard_avoid_flag = {
            "mechanical": "MECHANICAL",
            "structural": "STRUCTURAL",
            "unknown": "UNKNOWN_CONDITION",
        }.get(getattr(repair_assessment, "hard_avoid_reason", None), "MECHANICAL")
        if hard_avoid_flag not in risk_flags:
            risk_flags.append(hard_avoid_flag)
    # How much apply_repairs_to_max_bid actually deducted from the bid ceiling
    # (mirrors its own high-estimate-first fallback in shared/repair_pricing.py so
    # this always matches, whichever branch it took). Any profit figure that uses a
    # repair-ADJUSTED bid as its cost basis must subtract this same amount -- not
    # repair_cost_val (the plain mid estimate) -- or the two numbers mismatch and
    # profit stops tracking repair severity consistently. Figures that use a bid
    # basis which was never repair-adjusted (current price, expected auction price)
    # should keep using repair_cost_val, since nothing has deducted repairs from
    # those numbers yet.
    repair_deduction_for_bid = 0.0
    if recommended_max_bid_val is not None:
        repair_deduction_for_bid = float(
            repair_assessment.total_cost_high if repair_assessment.total_cost_high > 0 else repair_assessment.total_cost
        )
        adjusted_bid, repair_verdict = apply_repairs_to_max_bid(
            int(round(recommended_max_bid_val)),
            repair_assessment,
            vehicle_value=resale_mid_val or resale_mid,
        )
        recommended_max_bid_val = float(adjusted_bid)
    if repair_assessment.hard_avoid:
        recommended_max_bid_val = 0.0

    # Warn when comps data is missing or bid exceeds historical auction prices
    comps_median_val_float = _parse_currency(comps_median)
    if comps_count is None or comps_count == 0:
        if "NO_COMPS" not in risk_flags:
            risk_flags.append("NO_COMPS")
    elif comps_median_val_float is not None and recommended_max_bid_val is not None:
        if recommended_max_bid_val > comps_median_val_float * 1.05:  # 5% tolerance for rounding
            if "BIDS_ABOVE_COMPS" not in risk_flags:
                risk_flags.append("BIDS_ABOVE_COMPS")
    autotrader_curve_delta = _market_curve_delta(
        autotrader_median,
        carsales_estimate if carsales_estimate is not None else resale_mid_val,
    )
    if autotrader_curve_delta is not None and abs(autotrader_curve_delta) > AUTOTRADER_CURVE_WARNING_THRESHOLD:
        if AUTOTRADER_CURVE_WARNING_FLAG not in risk_flags:
            risk_flags.append(AUTOTRADER_CURVE_WARNING_FLAG)
        direction = "above" if autotrader_curve_delta > 0 else "below"
        notes.append(
            "Autotrader confirmation warning: median scraped listing price is "
            f"{abs(autotrader_curve_delta):.1%} {direction} the Carsales curve resale estimate."
        )
    repair_cost_val = float(repair_assessment.total_cost or 0.0)
    economic_max_bid_val = recommended_max_bid_val
    economic_cost_basis = economic_max_bid_val
    if economic_cost_basis is None:
        economic_cost_basis = current_price_val
    if economic_cost_basis is None:
        economic_cost_basis = 0.0
    economic_costs_map = _estimate_costs(economic_cost_basis, listing_data)
    economic_profit_mid_val = None
    if economic_max_bid_val is not None and resale_mid_val is not None and not repair_assessment.hard_avoid:
        economic_profit_mid_val = (
            resale_mid_val - sum(economic_costs_map.values()) - economic_max_bid_val - repair_deduction_for_bid
        )
    economic_profit_worst_val = None
    if economic_max_bid_val is not None and resale_low_val is not None and not repair_assessment.hard_avoid:
        economic_profit_worst_val = (
            resale_low_val - sum(economic_costs_map.values()) - economic_max_bid_val - repair_deduction_for_bid
        )
    economic_current_profit_val, economic_current_worst_profit_val = _profit_at_purchase_price(
        resale_mid_val or resale_mid,
        resale_low_val or resale_mid,
        current_price_val,
        listing_data,
        repair_cost_val,
    )
    if repair_assessment.hard_avoid:
        economic_current_profit_val = 0.0
        economic_current_worst_profit_val = 0.0
    bid_policy_gate = ""
    if "INTERSTATE" in risk_flags:
        recommended_max_bid_val = 0.0
        bid_policy_gate = "INTERSTATE"

    max_bid_mid_profit_val = None
    max_bid_worst_profit_val = None
    if recommended_max_bid_val is not None and not repair_assessment.hard_avoid:
        max_bid_mid_profit_val = (
            _net_profit_value(resale_mid_val or resale_mid, recommended_max_bid_val, listing_data) - repair_deduction_for_bid
        )
        max_bid_worst_profit_val = (
            _net_profit_value(resale_low_val or resale_mid, recommended_max_bid_val, listing_data) - repair_deduction_for_bid
        )
    if "INTERSTATE" in risk_flags:
        max_bid_mid_profit_val = 0.0
        max_bid_worst_profit_val = 0.0

    no_edge_at_current_bid = False
    if recommended_max_bid_val is not None and current_price_val is not None:
        no_edge_at_current_bid = recommended_max_bid_val <= current_price_val + EDGE_BUFFER

    # profit_bid_basis is recommended_max_bid_val (repair-adjusted) UNLESS the listing
    # has no bidding edge, in which case it falls back to current_price_val, which was
    # never repair-adjusted. Match the repair deduction to whichever basis is in use.
    profit_bid_basis = recommended_max_bid_val
    profit_bid_basis_is_repair_adjusted = True
    if (
        current_price_val is not None
        and profit_bid_basis is not None
        and profit_bid_basis <= current_price_val + EDGE_BUFFER
    ):
        profit_bid_basis = current_price_val
        profit_bid_basis_is_repair_adjusted = False

    cost_basis = profit_bid_basis if profit_bid_basis is not None else 0.0
    costs_map = _estimate_costs(cost_basis, listing_data)

    net_profit_mid_val = None
    net_profit_worst_val = None
    if profit_bid_basis is not None and not repair_assessment.hard_avoid:
        repair_deduction_for_basis = repair_deduction_for_bid if profit_bid_basis_is_repair_adjusted else repair_cost_val
        net_profit_mid_val = (
            _net_profit_value(resale_mid_val or resale_mid, profit_bid_basis, listing_data) - repair_deduction_for_basis
        )
        net_profit_worst_val = (
            _net_profit_value(resale_low_val or resale_mid, profit_bid_basis, listing_data) - repair_deduction_for_basis
        )
    if "INTERSTATE" in risk_flags:
        net_profit_mid_val = 0.0
        net_profit_worst_val = 0.0

    repair_low_val = repair_assessment.total_cost_low or repair_cost_val
    repair_high_val = repair_assessment.total_cost_high or repair_cost_val

    # Keep the legacy expected_profit field tied to the final max-bid basis.
    # Current-bid and expected-finish profit already have dedicated fields.
    expected_profit_val = max_bid_mid_profit_val
    expected_profit = _format_currency(expected_profit_val) if expected_profit_val is not None else None

    expected_auction_purchase_basis = expected_auction_price_val
    if (
        expected_auction_purchase_basis is not None
        and current_price_val is not None
        and current_price_val > expected_auction_purchase_basis
    ):
        expected_auction_purchase_basis = current_price_val
    expected_auction_profit_val = None
    expected_auction_worst_profit_val = None
    if expected_auction_purchase_basis is not None and not repair_assessment.hard_avoid:
        expected_auction_profit_val = (
            _net_profit_value(resale_mid_val or resale_mid, expected_auction_purchase_basis, listing_data)
            - repair_cost_val
        )
        expected_auction_worst_profit_val = (
            _net_profit_value(resale_low_val or resale_mid, expected_auction_purchase_basis, listing_data)
            - repair_cost_val
        )
    if "INTERSTATE" in risk_flags:
        expected_auction_profit_val = 0.0
        expected_auction_worst_profit_val = 0.0

    current_profit_val, current_worst_profit_val = _profit_at_purchase_price(
        resale_mid_val or resale_mid,
        resale_low_val or resale_mid,
        current_price_val,
        listing_data,
        repair_cost_val,
    )
    if repair_assessment.hard_avoid or ("INTERSTATE" in risk_flags):
        current_profit_val = 0.0
        current_worst_profit_val = 0.0
    current_profit_score = _profit_score(current_worst_profit_val, resale_mid_val)
    current_profit_label = _profit_label(current_worst_profit_val, resale_mid_val)
    expected_auction_profit_label = _profit_label(expected_auction_worst_profit_val, resale_mid_val)
    hard_max_safety = _hard_max_safety_label(max_bid_worst_profit_val)
    flip_difficulty, difficulty_reasons = _flip_difficulty(listing_data, repair_assessment, risk_flags)
    bid_status = _bid_status_label(current_price_val, expected_auction_price_val, recommended_max_bid_val)

    profit_margin = (
        _profit_margin_percent_text(net_profit_worst_val, resale_mid_val)
        or _profit_margin_percent_text(expected_profit_val, resale_mid_val)
    )
    margin_pct_value = (
        _profit_margin_percent_value(net_profit_worst_val, resale_mid_val)
        or _profit_margin_percent_value(expected_profit_val, resale_mid_val)
    )

    def _derive_verdict() -> str:
        if "INTERSTATE" in risk_flags:
            return "Avoid"
        if resale_low_val is None:
            return "Not Covered"
        if net_profit_worst_val is None or net_profit_worst_val <= 0:
            return "Avoid"
        if expected_profit_val is not None and expected_profit_val < MIN_EXPECTED_PROFIT_VIABILITY:
            return "Not Viable"
        if no_edge_at_current_bid:
            return "Trap"
        if expected_auction_worst_profit_val is not None and expected_auction_worst_profit_val < MIN_NET_PROFIT_ABSOLUTE:
            return "Marginal (expected finish)"
        if confidence_val >= 0.70 and net_profit_worst_val >= 3000:
            return "Strong Flip"
        if confidence_val >= 0.55 and net_profit_worst_val > 0:
            return "Conditional Flip"
        return "Trap"

    computed_verdict = _derive_verdict()
    if repair_assessment.hard_avoid:
        computed_verdict = "Avoid"
    elif repair_verdict == "Avoid":
        computed_verdict = "Avoid"
    elif repair_verdict == "Not Viable":
        computed_verdict = "Avoid"
    elif repair_verdict == "Marginal" and computed_verdict not in ("Avoid", "Trap", "Not Viable"):
        computed_verdict = "Marginal (repairs)"
    action_label = _action_label(
        computed_verdict,
        bid_status,
        expected_auction_worst_profit_val,
        current_worst_profit_val,
        hard_max_safety,
        comps_count=_parse_int(expected_auction_comps_count),
    )
    potential_buy_unresolved_repairs = bool(unresolved_repair_items and action_label == "Buy")
    if unresolved_repair_items:
        if action_label == "Avoid":
            computed_verdict = "Avoid (unresolved repairs)"
        else:
            computed_verdict = "Review (unresolved repairs)"
            action_label = "Review"
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
        "year": listing_row.get("year"),
        "make": listing_row.get("make"),
        "model": listing_row.get("model"),
        "variant": listing_row.get("variant"),
        "location": listing_row.get("location"),
        "analysis_timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "analysis_context": analysis_context,
        "carsales_price_estimate": _format_currency(resale_mid_val),
        "carsales_price_range": (
            f"{_format_currency(resale_low_val)} - {_format_currency(resale_high_val)}"
            if resale_low_val is not None and resale_high_val is not None
            else None
        ),
        "recommended_max_bid": _format_currency(recommended_max_bid_val) if recommended_max_bid_val is not None else None,
        "economic_max_bid": _format_currency(economic_max_bid_val) if economic_max_bid_val is not None else None,
        "economic_profit_mid": _format_currency(economic_profit_mid_val) if economic_profit_mid_val is not None else None,
        "economic_profit_worst": _format_currency(economic_profit_worst_val) if economic_profit_worst_val is not None else None,
        "economic_profit_at_current_bid": (
            _format_currency(economic_current_profit_val) if economic_current_profit_val is not None else None
        ),
        "economic_profit_at_current_bid_worst": (
            _format_currency(economic_current_worst_profit_val)
            if economic_current_worst_profit_val is not None
            else None
        ),
        "bid_policy_gate": bid_policy_gate,
        "expected_profit": expected_profit,
        "profit_margin_percent": profit_margin,
        "score_out_of_10": score_out_of_10,
        "confidence_notes": notes_value,
        "fees_estimate": _format_currency(costs_map["fees_estimate"]),
        "transport_estimate": _format_currency(costs_map["transport_estimate"]),
        "rego_estimate": _format_currency(costs_map["rego_estimate"]),
        "roadworthy_estimate": _format_currency(costs_map["roadworthy_estimate"]),
        "prep_estimate": _format_currency(costs_map["prep_estimate"]),
        "repair_estimate": _format_currency(repair_cost_val),
        "unresolved_repair_count": len(unresolved_repair_items),
        "unresolved_repairs": " | ".join(unresolved_repair_items),
        "potential_buy_unresolved_repairs": potential_buy_unresolved_repairs,
        "repair_estimate_low": _format_currency(repair_low_val),
        "repair_estimate_high": _format_currency(repair_high_val),
        "repair_estimate_low_value": repair_low_val,
        "repair_estimate_high_value": repair_high_val,
        "expected_auction_price": _format_currency(expected_auction_price_val),
        "expected_auction_bid_basis": _format_currency(expected_auction_purchase_basis),
        "expected_auction_profit": _format_currency(expected_auction_profit_val) if expected_auction_profit_val is not None else None,
        "expected_auction_worst_profit": _format_currency(expected_auction_worst_profit_val) if expected_auction_worst_profit_val is not None else None,
        "expected_auction_source": expected_auction_source,
        "expected_auction_comps_count": expected_auction_comps_count,
        "expected_auction_reauction_adjustment": (
            _format_currency(reauction_adjustment_val)
            if reauction_adjustment_val
            else None
        ),
        "expected_auction_reauction_reason": reauction_reason or None,
        "reauction_event_count": (
            reauction_context.get("reauction_event_count") if reauction_context else None
        ),
        "reauction_last_price": (
            _format_currency(reauction_context.get("reauction_last_price"))
            if reauction_context and reauction_context.get("reauction_last_price") is not None
            else None
        ),
        "reauction_price_delta": (
            _format_currency(reauction_context.get("reauction_price_delta"))
            if reauction_context and reauction_context.get("reauction_price_delta") is not None
            else None
        ),
        "expected_auction_price_q90": _format_currency(model_prediction["q90_price"]) if model_prediction else None,
        "expected_auction_price_q90_value": model_prediction["q90_price"] if model_prediction else None,
        "discount_used": DEFAULT_DISCOUNT,
        "profit_at_current_bid": _format_currency(current_profit_val) if current_profit_val is not None else None,
        "profit_at_current_bid_worst": _format_currency(current_worst_profit_val) if current_worst_profit_val is not None else None,
        "current_profit_score": current_profit_score,
        "current_profit_label": current_profit_label,
        "expected_auction_profit_label": expected_auction_profit_label,
        "hard_max_safety": hard_max_safety,
        "flip_difficulty": flip_difficulty,
        "difficulty_reasons": difficulty_reasons,
        "bid_status": bid_status,
        "action_label": action_label,
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
        "current_bid": listing_row.get("price"),
        "current_bid_numeric": current_price_val,
        "bids_observed": listing_row.get("bids"),
        "time_remaining_observed": listing_row.get("time_remaining_or_date_sold"),
        "valuation_input_hash": input_hash,
        "resale_low_value": resale_low_val,
        "resale_mid_value": resale_mid_val,
        "resale_high_value": resale_high_val,
        "recommended_max_bid_value": recommended_max_bid_val,
        "economic_max_bid_value": economic_max_bid_val,
        "net_profit_mid_value": net_profit_mid_val,
        "net_profit_worst_value": net_profit_worst_val,
        "expected_auction_price_value": expected_auction_price_val,
        "expected_auction_bid_basis_value": expected_auction_purchase_basis,
        "expected_auction_profit_value": expected_auction_profit_val,
        "expected_auction_worst_profit_value": expected_auction_worst_profit_val,
        "profit_at_current_bid_value": current_profit_val,
        "profit_at_current_bid_worst_value": current_worst_profit_val,
        "profit_margin_value": margin_pct_value,
    }

    _save_result_row(result_row)
    result_row["cached"] = False

    return result_row
