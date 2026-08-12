from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pytest

from shared import auction_model


class _FakeModel:
    def __init__(self, ratio: float):
        self.ratio = ratio

    def get_cat_feature_indices(self):
        return []

    def predict(self, pool):
        return np.array([self.ratio])


@pytest.fixture(autouse=True)
def _reset_model_cache(monkeypatch):
    monkeypatch.setattr(auction_model, "_models_available", None)
    monkeypatch.setattr(auction_model, "_q50_model", None)
    monkeypatch.setattr(auction_model, "_q90_model", None)
    monkeypatch.setattr(auction_model, "_feature_names", None)
    monkeypatch.setattr(auction_model, "_calibration_multiplier", None)
    monkeypatch.setattr(auction_model, "_q90_fallback_multiplier", None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (12000, 12000.0),
        (12000.5, 12000.5),
        ("125,000 km", 125000.0),
        ("  2.0  ", 2.0),
        ("not a number", None),
    ],
)
def test_parse_numeric(raw, expected) -> None:
    assert auction_model._parse_numeric(raw) == expected


def test_parse_numeric_nan_round_trips_to_nan() -> None:
    assert np.isnan(auction_model._parse_numeric(float("nan")))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "UNKNOWN"), (float("nan"), "UNKNOWN"), ("", "UNKNOWN"), ("  ", "UNKNOWN"), ("Toyota", "Toyota"), (5, "5")],
)
def test_str_or_unknown(raw, expected) -> None:
    assert auction_model._str_or_unknown(raw) == expected


def test_build_feature_row_derives_age_and_odometer_per_year() -> None:
    listing = {
        "year": "2018",
        "make": "Toyota",
        "odometer_reading": "120,000 km",
        "bids": "7",
        "location": "Laverton North VIC",
    }

    row = auction_model._build_feature_row(
        listing,
        comps_p50=20000.0,
        curve_tag="toyota_hilux",
        repair_tags=json.dumps(["body_exterior"]),
        repair_severity=12.0,
        decision_condition_only="BUY",
        estimated_parts_cost_aud=450.0,
        repair_tag_flags={"tag_body_exterior": 1},
        total_repair_tags=1,
    )

    expected_age = float(datetime.now(tz=timezone.utc).year - 2018)
    assert row["year"] == 2018.0
    assert row["year_int"] == 2018
    assert row["make"] == "Toyota"
    assert row["model"] == "UNKNOWN"
    assert row["odometer_numeric"] == 120000.0
    assert row["bids"] == 7.0
    assert row["comps_p50"] == 20000.0
    assert row["curve_tag"] == "toyota_hilux"
    assert row["location_x"] == "Laverton North VIC"
    assert row["vehicle_age_years"] == expected_age
    assert row["odometer_per_year"] == pytest.approx(120000.0 / expected_age)
    assert row["tag_body_exterior"] == 1
    assert row["total_repair_tags"] == 1


def test_build_feature_row_without_year_leaves_derived_fields_nan() -> None:
    row = auction_model._build_feature_row(
        {},
        comps_p50=10000.0,
        curve_tag="unknown",
        repair_tags="[]",
        repair_severity=0.0,
        decision_condition_only="UNKNOWN",
        estimated_parts_cost_aud=0.0,
        repair_tag_flags={},
        total_repair_tags=0,
    )

    assert np.isnan(row["year"])
    assert row["year_int"] is None
    assert np.isnan(row["vehicle_age_years"])
    assert np.isnan(row["odometer_per_year"])
    assert row["snapshot_status"] == "UNKNOWN"


def test_try_load_models_returns_false_when_artifacts_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(auction_model, "_MODEL_Q50_PATH", tmp_path / "q50.cbm")
    monkeypatch.setattr(auction_model, "_MODEL_Q90_PATH", tmp_path / "q90.cbm")
    monkeypatch.setattr(auction_model, "_FEATURES_PATH", tmp_path / "features.json")

    assert auction_model._try_load_models() is False
    assert auction_model.models_available() is False


def test_predict_auction_price_requires_positive_comps() -> None:
    assert auction_model.predict_auction_price({}, comps_p50=0.0, curve_tag="tag") is None
    assert auction_model.predict_auction_price({}, comps_p50=-1.0, curve_tag="tag") is None


def test_predict_auction_price_returns_none_when_models_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(auction_model, "_try_load_models", lambda: False)

    assert auction_model.predict_auction_price({}, comps_p50=10000.0, curve_tag="tag") is None


def _install_fake_models(monkeypatch, *, q50_ratio: float, q90_ratio: float, calibration: float = 1.0) -> None:
    monkeypatch.setattr(auction_model, "_try_load_models", lambda: True)
    monkeypatch.setattr(auction_model, "_q50_model", _FakeModel(q50_ratio))
    monkeypatch.setattr(auction_model, "_q90_model", _FakeModel(q90_ratio))
    monkeypatch.setattr(auction_model, "_feature_names", ["comps_p50", "repair_severity", "missing_feature"])
    monkeypatch.setattr(auction_model, "_calibration_multiplier", calibration)
    monkeypatch.setattr(auction_model, "_q90_fallback_multiplier", 1.35)


def test_predict_auction_price_scales_and_rounds_predictions(monkeypatch) -> None:
    _install_fake_models(monkeypatch, q50_ratio=0.8123, q90_ratio=1.0, calibration=1.1)

    result = auction_model.predict_auction_price({"year": "2018"}, comps_p50=20000.0, curve_tag="tag")

    assert result["source"] == "catboost_model"
    assert result["predicted_ratio"] == pytest.approx(0.8123)
    assert result["comps_p50"] == 20000.0
    assert result["calibration_multiplier"] == 1.1
    assert result["q50_price"] == 16250  # 16246 rounded to nearest $10
    assert result["q90_price"] == 22000


def test_predict_auction_price_guards_quantile_crossing(monkeypatch) -> None:
    _install_fake_models(monkeypatch, q50_ratio=1.0, q90_ratio=0.5)

    result = auction_model.predict_auction_price({}, comps_p50=10000.0, curve_tag="tag")

    assert result["q50_price"] == 10000
    assert result["q90_price"] == 13500  # q50 * fallback multiplier


def test_predict_auction_price_swallows_inference_errors(monkeypatch) -> None:
    _install_fake_models(monkeypatch, q50_ratio=1.0, q90_ratio=1.2)

    class _Exploding(_FakeModel):
        def predict(self, pool):
            raise RuntimeError("inference failed")

    monkeypatch.setattr(auction_model, "_q50_model", _Exploding(1.0))

    assert auction_model.predict_auction_price({}, comps_p50=10000.0, curve_tag="tag") is None
