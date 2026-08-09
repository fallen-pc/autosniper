from __future__ import annotations

import pandas as pd

from scripts.readiness_smoke import validate_materialized_views


def test_validate_materialized_views_accepts_consistent_state():
    datasets = {
        "vehicle_static_details.csv": pd.DataFrame(
            [{"url": "a"}, {"url": "b"}, {"url": "c"}]
        ),
        "vehicle_state.csv": pd.DataFrame(
            [
                {"url": "a", "state": "active"},
                {"url": "b", "state": "sold"},
                {"url": "c", "state": "withdrawn"},
            ]
        ),
        "active_vehicle_details.csv": pd.DataFrame([{"url": "a"}]),
        "sold_cars.csv": pd.DataFrame([{"url": "b"}]),
        "referred_cars.csv": pd.DataFrame([{"url": "c"}]),
        "active_vehicle_links.csv": pd.DataFrame([{"url": "a"}]),
    }

    assert validate_materialized_views(datasets) == []


def test_validate_materialized_views_accepts_static_parsed_state_when_active_queue_contains_url():
    datasets = {
        "vehicle_static_details.csv": pd.DataFrame([{"url": "a"}]),
        "vehicle_state.csv": pd.DataFrame([{"url": "a", "state": "static_parsed"}]),
        "active_vehicle_details.csv": pd.DataFrame([{"url": "a"}]),
        "sold_cars.csv": pd.DataFrame(),
        "referred_cars.csv": pd.DataFrame(),
        "active_vehicle_links.csv": pd.DataFrame([{"url": "a"}]),
    }

    assert validate_materialized_views(datasets) == []


def test_validate_materialized_views_flags_terminal_state_mismatch():
    datasets = {
        "vehicle_static_details.csv": pd.DataFrame([{"url": "a"}, {"url": "b"}]),
        "vehicle_state.csv": pd.DataFrame(
            [
                {"url": "a", "state": "active"},
                {"url": "b", "state": "sold"},
            ]
        ),
        "active_vehicle_details.csv": pd.DataFrame([{"url": "b"}]),
        "sold_cars.csv": pd.DataFrame(),
        "referred_cars.csv": pd.DataFrame(),
        "active_vehicle_links.csv": pd.DataFrame([{"url": "a"}]),
    }

    errors = validate_materialized_views(datasets)
    assert any("marked terminal in vehicle_state.csv" in error for error in errors)
