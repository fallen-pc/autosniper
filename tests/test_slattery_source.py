"""Public payload regression; fixture omits contacts, media and bidder identities."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from shared.slattery_source import (
    canonical_slattery_url,
    extract_slattery_listing,
    extract_slattery_records,
    match_slattery_record,
    normalize_slattery_url,
    slattery_listing_identity,
)


NUMERIC = "https://slatteryauctions.com.au/assets/137614?auctionId=10301"
ALPHA = "https://www.slatteryauctions.com.au/assets/02iOa00000EHP8PIAX?auctionId=a0lOa00000PfsvhIAB"
NOW = datetime(2026, 9, 9, 4, 9, tzinfo=timezone.utc)


@pytest.fixture
def asset():
    return json.loads((Path(__file__).parent / "fixtures" / "slattery_asset.json").read_text(encoding="utf8"))


def flight(asset, *, route="137614?auctionId=10301", related=None):
    root = {"c": ["", "assets", route], "children": {"asset": asset, "relatedAssets": related or []}}
    # Actual Next output contains unnamed preload rows and a byte-length framed
    # text row immediately before the asset JSON, often across script chunks.
    raw_text = 'Résumé\nff:{"asset":{"id":999,"auctionId":999,"name":"not JSON data"}}'
    stream = ':HL["/font.woff2","font"]\n1:T' + format(len(raw_text.encode("utf8")), "x") + "," + raw_text + "2:" + json.dumps(root) + "\n"
    parts = [stream[:85], stream[85:217], stream[217:]]
    return "<html>" + "".join("<script>self.__next_f.push(" + json.dumps([1, part]) + ")</script>" for part in parts) + "</html>"


def extract(asset, *, now=NOW, **kwargs):
    return extract_slattery_listing(flight(asset, **kwargs), NUMERIC, now=now)


def test_real_shaped_hydration_and_identity_fields(asset):
    row = extract(asset)
    assert row["url"] == NUMERIC
    assert (row["year"], row["make"], row["model"]) == ("2018", "Toyota", "RAV4")
    assert "ZSA42R" in row["variant"] and "FWD" in row["variant"]
    assert row["vin"] == "TESTVIN1234567890"
    assert row["odometer_reading"] == "52089"
    assert row["location"] == "Karratha, WA"
    assert row["transmission"] == "CVT"
    assert row["spare_key"] == "No"
    assert row["price"] == "16200"
    assert row["detail_completeness_status"] == "complete"


def test_alpha_and_numeric_aliases_require_route_matched_asset_and_auction(asset):
    html = flight(asset, route=ALPHA.split("/assets/", 1)[1])
    records = extract_slattery_records(html)
    assert len(records) == 1
    assert canonical_slattery_url(ALPHA, records) == NUMERIC
    assert extract_slattery_listing(html, ALPHA, now=NOW)["url"] == NUMERIC
    assert match_slattery_record(NUMERIC.replace("10301", "10302"), records) is None
    assert match_slattery_record(ALPHA.replace("PfsvhIAB", "OtherIAB"), records) is None


def test_numeric_auction_route_mismatch_does_not_create_alias(asset):
    records = extract_slattery_records(flight(asset, route="137614?auctionId=10302"))
    assert match_slattery_record(NUMERIC.replace("10301", "10302"), records) is None


def test_missing_explicit_auction_alias_does_not_merge_alpha_by_asset_only(asset):
    assert canonical_slattery_url(ALPHA, extract_slattery_records(flight(asset))) == normalize_slattery_url(ALPHA)
    assert extract_slattery_listing(flight(asset), ALPHA, now=NOW) == {}


def test_unrelated_route_and_lookalike_title_do_not_supply_alias(asset):
    records = extract_slattery_records(flight(asset, route="02iOa00000OTHERIAX?auctionId=a0lOa00000OtherIAB"))
    assert match_slattery_record(ALPHA, records) is None
    other = deepcopy(asset)
    other["id"] = 999
    other["sfid"] = "02iOa00000OTHERIAX"
    assert extract_slattery_listing(flight(other), NUMERIC, now=NOW) == {}


def test_conflicting_asset_records_fail_closed(asset):
    conflicting = deepcopy(asset)
    conflicting["odometer"] = 999999
    document = json.dumps({"data": [asset, conflicting]})
    assert extract_slattery_listing(document, NUMERIC, now=NOW) == {}


def test_wrong_main_detail_does_not_use_requested_lot_from_related_cards(asset):
    other = deepcopy(asset)
    other["id"] = 999999
    other["sfid"] = "02iOa00000OTHERIAX"
    assert extract_slattery_listing(flight(other, related=[asset]), NUMERIC, now=NOW) == {}


def test_api_json_and_next_data_support_scoped_records(asset):
    for document in [json.dumps({"data": [asset]}), '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"assets": [asset]}}) + "</script>"]:
        assert len(extract_slattery_records(document)) == 1
        assert extract_slattery_listing(document, NUMERIC, now=NOW)["price"] == "16200"


def test_malformed_or_embedded_free_text_is_not_json_evidence(asset):
    assert extract_slattery_records('price 99999 ' + json.dumps(asset)) == []
    assert extract_slattery_listing(flight(asset)[:300], NUMERIC, now=NOW) == {}


def test_referral_unwrap_preserves_unknown_parameters_and_drops_only_marketing():
    destination = ALPHA + "&utm_source=grays&utm_content=RAV4+GX&sellerRef=a%2Bb&mode=extended"
    wrapped = "https://www.grays.com/redirection/interimPage?url=" + quote(destination, safe="")
    clean = normalize_slattery_url(wrapped)
    assert clean == ALPHA.replace("www.slattery", "slattery") + "&sellerRef=a%2Bb&mode=extended"
    assert slattery_listing_identity(wrapped) == ("02iOa00000EHP8PIAX", "a0lOa00000PfsvhIAB")


@pytest.mark.parametrize("url", [
    "https://slatteryauctions.com.au.attacker.test/assets/137614?auctionId=10301",
    "https://slatteryauctions.com.au@attacker.test/assets/137614?auctionId=10301",
    "https://attacker.test/redirection/interimPage?url=" + quote(NUMERIC, safe=""),
    "https://www.grays.com/other?url=" + quote(NUMERIC, safe=""),
    "https://www.grays.com/redirection/interimPage?url=https%3A%2F%2Fattacker.test",
    NUMERIC + "&auctionId=999",
    "http://slatteryauctions.com.au/assets/137614?auctionId=10301",
    "https://slatteryauctions.com.au/assets/137614",
])
def test_bad_referrals_and_ambiguous_identities_are_rejected(url):
    assert normalize_slattery_url(url) == ""


def test_canonicalization_retains_full_url_context(asset):
    html = flight(asset, route=ALPHA.split("/assets/", 1)[1])
    assert canonical_slattery_url(ALPHA + "&view=a%2Bb#details", extract_slattery_records(html)) == NUMERIC + "&view=a%2Bb#details"


def test_bids_are_scoped_to_asset_and_auction_cycle(asset):
    asset["auctionAssetBids"].extend([
        {"assetId": 999999, "auctionId": 10301, "bidAmount": 999999},
        {"assetId": 137614, "auctionId": 99999, "bidAmount": 888888},
        {"assetId": 137614, "bidAmount": 777777},
    ])
    assert extract(asset)["price"] == "16200"


def test_explicit_current_bid_precedes_higher_bid_history(asset):
    asset["currentBidAmount"] = 15000
    assert extract(asset)["price"] == "15000"


def test_starting_bid_is_only_used_with_explicit_zero_bid_count(asset):
    asset["auctionAssetBids"] = []
    asset["bidCount"] = 0
    assert extract(asset)["price"] == "1000"
    asset["bidCount"] = None
    assert extract(asset)["price"] == ""


def test_closed_is_not_a_verified_sale_even_with_sale_price_field(asset):
    asset["salePrice"] = 16200
    asset["boughtAt"] = "2026-09-09T04:08:00Z"
    row = extract(asset)
    assert row["status"] == "Closed"
    assert row["final_sale_price"] == row["date_sold"] == ""


def test_timed_auction_requires_verified_status_code_and_sale_type(asset):
    during = datetime(2026, 9, 8, tzinfo=timezone.utc)
    assert extract(asset, now=during)["status"] == "Active"
    asset["assetStatusId"] = 12
    assert extract(asset, now=during)["status"] == "Active"
    asset["assetStatusId"] = 999
    row = extract(asset, now=during)
    assert row["status"] == ""
    assert row["detail_completeness_status"] == "incomplete"
    closed = extract(asset)
    assert closed["status"] == "Closed"
    assert closed["final_sale_price"] == closed["date_sold"] == ""
    asset["assetStatusId"] = 7
    asset["saleTypeId"] = 2
    assert extract(asset, now=during)["status"] == ""


def test_bonus_time_uses_only_scoped_bids_and_explicit_extension(asset):
    asset["auctionAssetBids"][-1]["bidAt"] = "2026-09-09T04:07:30Z"
    row = extract(asset)
    assert row["status"] == "Active"
    assert row["time_remaining_or_date_sold"] == "2026-09-09T04:09:30Z"
    asset["lastAssetClosesAt"] = "2026-09-09T04:11:00Z"
    assert extract(asset)["time_remaining_or_date_sold"] == "2026-09-09T04:11:00Z"
    asset["auctionAssetBids"].append({"assetId": 999999, "auctionId": 10301, "bidAmount": 99999, "bidAt": "2026-09-11T04:11:00Z"})
    assert extract(asset)["time_remaining_or_date_sold"] == "2026-09-09T04:11:00Z"


def test_upcoming_and_withdrawn_are_never_active(asset):
    assert extract(asset, now=datetime(2026, 9, 1, tzinfo=timezone.utc))["status"] == "Upcoming"
    asset["status"] = "Withdrawn"
    assert extract(asset, now=datetime(2026, 9, 8, tzinfo=timezone.utc))["status"] == "Withdrawn"


def test_interstate_registration_and_detailed_damage_are_retained(asset):
    row = extract(asset)
    assert row["rego_expiry"] == "Unregistered for interstate buyers"
    assert "WA Licence Holders" in row["general_condition"]
    assert "Seat (passenger)) - Stains" in row["general_condition"]
    assert "Rego Expiry" in row["general_condition"]
    assert "2018 TOYOTA RAV4" not in row["general_condition"]


def test_missing_condition_and_location_state_fail_even_with_rego_notes(asset):
    asset["conditionAttributes"] = {}
    asset["siteMaster"] = {"name": "Karratha"}
    row = extract(asset)
    assert row["detail_completeness_status"] == "incomplete"
    assert "general_condition" in row["detail_fields_missing"]
    assert "location_state" in row["detail_fields_missing"]


def test_description_sold_unregistered_does_not_mark_a_sale(asset):
    asset["description"] = "Vehicle sold as is, unregistered."
    asset["detailAttributes"].pop("soldunregistered")
    row = extract(asset)
    assert row["rego_expiry"] == "Unregistered"
    assert row["status"] == "Closed"
    assert row["date_sold"] == ""


def test_fee_evidence_is_bound_to_same_matched_asset_and_canonical_url(asset):
    row = extract_slattery_listing(flight(asset, route=ALPHA.split("/assets/", 1)[1]), ALPHA, now=NOW)
    assert row["auction_fee_status"] == "verified_schedule"
    assert json.loads(row["auction_fee_schedule"])["listing_url"] == NUMERIC
    related = deepcopy(asset)
    related["id"] = 999999
    related["sfid"] = "02iOa00000OTHERIAX"
    asset["chargePrices"] = []
    row = extract(asset, related=[related])
    assert row["auction_fee_status"] == "missing"
    assert row["auction_fee_schedule"] == ""


@pytest.mark.parametrize("restriction", ["regoplatestolicenseddealersonly", "regoplatestolicnswdealersonly"])
@pytest.mark.parametrize("sold_unregistered", ["True", "False"])
def test_dealer_registration_restriction_keeps_private_buyer_roadworthy_cost(asset, restriction, sold_unregistered, monkeypatch):
    from scripts import ai_listing_valuation as valuation

    monkeypatch.setattr(valuation, "OPERATING_STATE", "VIC")
    asset["description"] = "Vehicle sold registered."
    asset["detailAttributes"]["soldunregistered"] = sold_unregistered
    asset["detailAttributes"][restriction] = "True"
    row = extract(asset)

    assert row["auction_fee_status"] == "verified_schedule"
    assert row["rego_no"] == "TEST001"
    assert row["rego_expiry"] == "Unregistered for private buyers; registration restricted to licensed dealers"
    assert "Registration plates restricted to licensed" in row["general_condition"]
    if restriction == "regoplatestolicnswdealersonly":
        assert "licensed NSW dealers" in row["general_condition"]
    costs = valuation._estimate_bid_cost_components(6000, row)
    assert costs["roadworthy_cost"] == valuation.ROADWORTHY_ESTIMATE > 0
    assert costs["transfer_fee"] == 0
