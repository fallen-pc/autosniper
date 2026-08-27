from __future__ import annotations

import pytest

from scripts import ai_listing_valuation as val


@pytest.mark.parametrize(
    ("location", "expected_state"),
    [
        ("140-152 National Drive, Dandenong South, 3175", "VIC"),
        ("3 Maxwell Rd, Pooraka, 5095", "SA"),
        ("Jandakot", "WA"),
        ("Brisbane, Queensland", "QLD"),
        ("Fyshwick 2609", "ACT"),
        ("Darwin 0800", "NT"),
    ],
)
def test_state_inference_handles_live_location_formats(
    location: str,
    expected_state: str,
) -> None:
    assert val._state_from_text(location) == expected_state


def test_postcode_inference_drives_transport_and_interstate_gate(monkeypatch) -> None:
    monkeypatch.setattr(val, "INTERSTATE_BUYING_ALLOWED", False)
    monkeypatch.setattr(val, "INTERSTATE_ALLOWED_STATES", None)

    pooraka = {"location": "3 Maxwell Rd, Pooraka, 5095"}
    dandenong = {"location": "140-152 National Drive, Dandenong South, 3175"}

    assert val._estimate_transport_cost(pooraka["location"]) == val.INTERSTATE_TRANSPORT_COSTS["SA"]
    assert val._interstate_purchase_blocked(pooraka) is True
    assert val._estimate_transport_cost(dandenong["location"]) == val.DEFAULT_TRANSPORT
    assert val._interstate_purchase_blocked(dandenong) is False


def test_suburb_only_jandakot_is_treated_as_wa(monkeypatch) -> None:
    monkeypatch.setattr(val, "INTERSTATE_BUYING_ALLOWED", False)
    monkeypatch.setattr(val, "INTERSTATE_ALLOWED_STATES", None)

    listing = {"location": "Jandakot"}

    assert val._estimate_transport_cost(listing["location"]) == val.INTERSTATE_TRANSPORT_COSTS["WA"]
    assert val._interstate_purchase_blocked(listing) is True


def test_registered_grays_costs_include_duty_transfer_and_admin_fee() -> None:
    listing = {
        "url": "https://www.grays.com/lot/example",
        "location": "Dandenong South 3175",
        "rego_expiry": "2027-01-01",
        "rego_no": "ABC123",
        "body_type": "Hatch",
    }

    components = val._estimate_bid_cost_components(5_000.0, listing)

    assert components["auction_fee"] == 650.0
    assert components["motor_vehicle_duty"] == 210.0
    assert components["transfer_fee"] == 47.50
    assert components["administration_fee"] == 49.50
    assert components["fees_total"] == 957.0
    assert val._estimate_costs(5_000.0, listing)["fees_estimate"] == 957.0


def test_unregistered_grays_costs_omit_transfer_but_keep_duty_and_admin() -> None:
    listing = {
        "url": "https://www.grays.com/lot/example",
        "location": "Dandenong South 3175",
        "rego_expiry": "Unregistered",
        "rego_no": "",
        "body_type": "Hatch",
    }

    components = val._estimate_bid_cost_components(5_001.0, listing)

    assert components["auction_fee"] == 710.0
    assert components["motor_vehicle_duty"] == pytest.approx(218.40)
    assert components["transfer_fee"] == 0.0
    assert components["administration_fee"] == 49.50
    assert components["fees_total"] == pytest.approx(977.90)
    assert components["roadworthy_cost"] == val.ROADWORTHY_ESTIMATE


def test_non_grays_listing_does_not_get_grays_admin_fee() -> None:
    components = val._estimate_bid_cost_components(
        5_000.0,
        {"url": "https://example.com/vehicle", "rego_expiry": "Unregistered"},
    )

    assert components["administration_fee"] == 0.0


@pytest.mark.parametrize(
    ("dutiable_value", "expected_duty"),
    [
        (80_567.0, 3_385.20),
        (80_568.0, 4_191.20),
        (100_001.0, 7_014.00),
        (150_001.0, 13_518.00),
    ],
)
def test_victorian_duty_uses_current_passenger_vehicle_bands(
    dutiable_value: float,
    expected_duty: float,
) -> None:
    assert val._victorian_motor_vehicle_duty(dutiable_value) == pytest.approx(expected_duty)