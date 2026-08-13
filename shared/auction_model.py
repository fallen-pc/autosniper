"""Lazy-loading inference wrapper for the CatBoost auction price correction model.

The model predicts:
    auction_ratio = auction_close_price / comps_p50

At inference:
    1. comps_p50 comes from the live page's groupby-median (sold_stats_group)
    2. We build a feature row from the active listing + repair features
    3. predicted_price = model.predict(ratio) * comps_p50
    4. q90 price is multiplied by the calibration_multiplier stored in metrics JSON

Falls back gracefully to None if model files are missing or CatBoost is unavailable,
so the caller can fall through to the legacy comps_median path.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"
_MODEL_Q50_PATH = _ARTIFACTS / "auction_ratio_q50.cbm"
_MODEL_Q90_PATH = _ARTIFACTS / "auction_ratio_q90.cbm"
_FEATURES_PATH = _ARTIFACTS / "feature_names.json"
_METRICS_PATH = _ARTIFACTS / "correction_model_metrics.json"

# Module-level cache so models are loaded once per process
_q50_model = None
_q90_model = None
_feature_names: list[str] | None = None
_calibration_multiplier: float | None = None
_q90_fallback_multiplier: float | None = None
_models_available: bool | None = None  # None = unchecked


def _try_load_models() -> bool:
    global _q50_model, _q90_model, _feature_names, _calibration_multiplier, _q90_fallback_multiplier, _models_available

    if _models_available is not None:
        return _models_available

    if not (_MODEL_Q50_PATH.exists() and _MODEL_Q90_PATH.exists() and _FEATURES_PATH.exists()):
        _models_available = False
        return False

    try:
        from catboost import CatBoostRegressor

        q50 = CatBoostRegressor()
        q50.load_model(str(_MODEL_Q50_PATH))

        q90 = CatBoostRegressor()
        q90.load_model(str(_MODEL_Q90_PATH))

        with open(_FEATURES_PATH, encoding="utf-8") as fh:
            features = json.load(fh)

        calibration_multiplier = 1.0
        q90_fallback_multiplier = 1.35  # conservative default if not in metrics
        if _METRICS_PATH.exists():
            with open(_METRICS_PATH, encoding="utf-8") as fh:
                metrics = json.load(fh)
            calibration_multiplier = float(metrics.get("calibration_multiplier", 1.0))
            q90_fallback_multiplier = float(metrics.get("q90_fallback_multiplier", 1.35))

        _q50_model = q50
        _q90_model = q90
        _feature_names = features
        _calibration_multiplier = calibration_multiplier
        _q90_fallback_multiplier = q90_fallback_multiplier
        _models_available = True
        return True

    except Exception as exc:  # noqa: BLE001 - model load failures degrade to curve-only pricing
        logger.error(
            "Auction model load failed (%s: %s); valuations fall back to curve-only pricing.",
            type(exc).__name__,
            exc,
        )
        _models_available = False
        return False


def _parse_numeric(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not (isinstance(value, float) and pd.isna(value)):
        return float(value)
    text = str(value).lower().replace("km", "").replace(",", "").strip()
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def _str_or_unknown(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, float) and pd.isna(value):
        return "UNKNOWN"
    text = str(value).strip()
    return text if text else "UNKNOWN"


def _build_feature_row(
    listing: Mapping[str, Any],
    *,
    comps_p50: float,
    curve_tag: str,
    repair_tags: str,
    repair_severity: float,
    decision_condition_only: str,
    estimated_parts_cost_aud: float,
    repair_tag_flags: dict[str, int],
    total_repair_tags: int,
) -> dict[str, Any]:
    """Build a feature dict matching the training schema."""

    odometer_numeric = _parse_numeric(
        listing.get("odometer_numeric") or listing.get("odometer_reading")
    )
    bids_numeric = _parse_numeric(listing.get("bids_numeric") or listing.get("bids"))
    year_val = _parse_numeric(listing.get("year"))
    year_int = int(year_val) if year_val is not None else None

    now = datetime.now(tz=timezone.utc)
    vehicle_age_years: Optional[float] = None
    odometer_per_year: Optional[float] = None
    if year_int is not None and year_int > 1900:
        vehicle_age_years = float(now.year - year_int) or None
        if vehicle_age_years and odometer_numeric:
            odometer_per_year = odometer_numeric / vehicle_age_years

    return {
        # Core vehicle fields — numeric features must be float/NaN, not string
        "year": float(year_int) if year_int else np.nan,  # float feature
        "make": _str_or_unknown(listing.get("make")),
        "model": _str_or_unknown(listing.get("model")),
        "variant": _str_or_unknown(listing.get("variant")),
        "body_type": _str_or_unknown(listing.get("body_type")),
        "transmission": _str_or_unknown(listing.get("transmission")),
        "fuel_type": _str_or_unknown(listing.get("fuel_type")),
        "odometer_reading": odometer_numeric if odometer_numeric else np.nan,  # float feature
        "no_of_seats": _parse_numeric(listing.get("no_of_seats")) or np.nan,  # float feature
        "rego_expiry": _str_or_unknown(listing.get("rego_expiry")),
        "no_of_cylinders": _parse_numeric(listing.get("no_of_cylinders")) or np.nan,  # float feature
        "engine_capacity": _parse_numeric(listing.get("engine_capacity")) or np.nan,  # float feature
        "exterior_colour": _str_or_unknown(listing.get("exterior_colour")),
        "interior_colour": _str_or_unknown(listing.get("interior_colour")),
        "key": _str_or_unknown(listing.get("key")),
        "spare_key": _str_or_unknown(listing.get("spare_key")),
        "owners_manual": _str_or_unknown(listing.get("owners_manual")),
        "service_history": _str_or_unknown(listing.get("service_history")),
        "engine_turns_over": _str_or_unknown(listing.get("engine_turns_over")),
        # Location
        "location_x": _str_or_unknown(listing.get("location") or listing.get("location_x")),
        # Auction fields — bids is float feature
        "bids": bids_numeric if bids_numeric else np.nan,  # float feature
        "odometer_numeric": odometer_numeric,
        "bids_numeric": bids_numeric,
        # Tags
        "canonical_tag": _str_or_unknown(listing.get("canonical_tag")),
        "curve_tag": _str_or_unknown(curve_tag),
        "year_int": year_int,
        # Baseline — this is the key feature the model corrects around
        "comps_p50": comps_p50,
        # Repair features
        "repair_tags": _str_or_unknown(repair_tags),
        "repair_severity": repair_severity,
        "decision_condition_only": _str_or_unknown(decision_condition_only),
        "estimated_parts_cost_aud": estimated_parts_cost_aud,
        **repair_tag_flags,
        "total_repair_tags": total_repair_tags,
        # Temporal — use today as sold date proxy (listing is about to close)
        "date_sold_parsed": pd.Timestamp(now),
        "vehicle_year_numeric": float(year_int) if year_int else np.nan,
        "vehicle_age_years": vehicle_age_years if vehicle_age_years else np.nan,
        "odometer_per_year": odometer_per_year if odometer_per_year else np.nan,
        # Snapshot features — unavailable for active listings
        "snapshot_ts": np.nan,
        "snapshot_price_numeric": np.nan,
        "snapshot_bids_numeric": np.nan,
        "time_remaining_text": _str_or_unknown(listing.get("time_remaining_or_date_sold")),
        "snapshot_time_remaining_hours": np.nan,
        "snapshot_status": "UNKNOWN",
        "location_y": "UNKNOWN",
        "snapshot_location_state": "UNKNOWN",
        "auction_site": "UNKNOWN",
        "snapshot_hours_to_close": np.nan,
        # Day-of-week / month seasonality: use today since listing closes soon
        "sold_dow": now.weekday(),
        "sold_month": now.month,
        "sold_year": now.year,
    }


def predict_auction_price(
    listing: Mapping[str, Any],
    *,
    comps_p50: float,
    curve_tag: str,
    repair_tags: str = "[]",
    repair_severity: float = 0.0,
    decision_condition_only: str = "UNKNOWN",
    estimated_parts_cost_aud: float = 0.0,
    repair_tag_flags: dict[str, int] | None = None,
    total_repair_tags: int = 0,
) -> Optional[dict[str, Any]]:
    """Predict auction close price using the CatBoost model.

    Returns a dict with keys:
        q50_price       -- median price prediction (AUD)
        q90_price       -- upper bound prediction, calibration-adjusted (AUD)
        predicted_ratio -- raw q50 ratio prediction
        source          -- "catboost_model"
        calibration_multiplier

    Returns None if model is unavailable or comps_p50 <= 0.
    """
    if comps_p50 <= 0:
        return None
    if not _try_load_models():
        return None

    if repair_tag_flags is None:
        repair_tag_flags = {}

    row = _build_feature_row(
        listing,
        comps_p50=comps_p50,
        curve_tag=curve_tag,
        repair_tags=repair_tags,
        repair_severity=repair_severity,
        decision_condition_only=decision_condition_only,
        estimated_parts_cost_aud=estimated_parts_cost_aud,
        repair_tag_flags=repair_tag_flags,
        total_repair_tags=total_repair_tags,
    )

    # Build DataFrame with exactly the training feature columns in order
    try:
        from catboost import Pool

        df = pd.DataFrame([row])
        # Add any missing columns as NaN/UNKNOWN
        for col in _feature_names:
            if col not in df.columns:
                df[col] = np.nan
        df = df[_feature_names]

        cat_feature_indices = _q50_model.get_cat_feature_indices()
        cat_cols = [_feature_names[i] for i in cat_feature_indices]

        for col in cat_cols:
            df[col] = df[col].fillna("UNKNOWN").astype(str)

        pool = Pool(data=df, feature_names=_feature_names, cat_features=cat_feature_indices)
        q50_ratio = float(_q50_model.predict(pool)[0])
        q90_ratio = float(_q90_model.predict(pool)[0])

        q50_price = comps_p50 * q50_ratio
        q90_price_raw = comps_p50 * q90_ratio * (_calibration_multiplier or 1.0)

        # Guard against quantile crossing (q90 < q50 in sparse feature regions)
        if q90_price_raw < q50_price:
            q90_price = q50_price * (_q90_fallback_multiplier or 1.35)
        else:
            q90_price = q90_price_raw

        return {
            "q50_price": round(q50_price / 10) * 10,  # round to $10
            "q90_price": round(q90_price / 10) * 10,
            "predicted_ratio": q50_ratio,
            "source": "catboost_model",
            "calibration_multiplier": _calibration_multiplier,
            "comps_p50": comps_p50,
        }
    except Exception as exc:  # noqa: BLE001 - prediction failures degrade to curve-only pricing
        logger.error(
            "Auction model prediction failed (%s: %s); returning no model prediction.",
            type(exc).__name__,
            exc,
        )
        return None


def models_available() -> bool:
    """Return True if the CatBoost models are loaded and ready."""
    return _try_load_models()
