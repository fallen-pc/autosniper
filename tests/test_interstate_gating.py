from __future__ import annotations

import pytest

from scripts import ai_listing_valuation as val


def test_transport_cost_local_state_uses_default() -> None:
    assert val._estimate_transport_cost("vic") == val.DEFAULT_TRANSPORT
    assert val._estimate_transport_cost(None) == val.DEFAULT_TRANSPORT
    assert val._estimate_transport_cost("Sunshine VIC 3020") == val.DEFAULT_TRANSPORT


@pytest.mark.parametrize(
    "location, expected_state",
    [("nsw", "NSW"), ("Brisbane QLD", "QLD"), ("wa", "WA"), ("tas", "TAS")],
)
def test_transport_cost_interstate_uses_lane_table(location: str, expected_state: str) -> None:
    assert val._estimate_transport_cost(location) == val.INTERSTATE_TRANSPORT_COSTS[expected_state]
    assert val._estimate_transport_cost(location) > val.DEFAULT_TRANSPORT


def test_interstate_blocked_when_flag_off(monkeypatch) -> None:
    monkeypatch.setattr(val, "INTERSTATE_BUYING_ALLOWED", False)
    monkeypatch.setattr(val, "INTERSTATE_ALLOWED_STATES", None)
    assert val._interstate_purchase_blocked({"location": "nsw"}) is True
    assert val._interstate_purchase_blocked({"location": "vic"}) is False


def test_interstate_allowlist_gates_per_state(monkeypatch) -> None:
    monkeypatch.setattr(val, "INTERSTATE_BUYING_ALLOWED", True)
    monkeypatch.setattr(val, "INTERSTATE_ALLOWED_STATES", frozenset({"NSW", "QLD"}))
    assert val._interstate_purchase_blocked({"location": "nsw"}) is False
    assert val._interstate_purchase_blocked({"location": "qld"}) is False
    assert val._interstate_purchase_blocked({"location": "wa"}) is True
    assert val._interstate_purchase_blocked({"location": "vic"}) is False


def test_interstate_all_states_when_boolean_true(monkeypatch) -> None:
    monkeypatch.setattr(val, "INTERSTATE_BUYING_ALLOWED", True)
    monkeypatch.setattr(val, "INTERSTATE_ALLOWED_STATES", None)
    assert val._interstate_purchase_blocked({"location": "wa"}) is False
