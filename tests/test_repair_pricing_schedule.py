import pandas as pd

from shared.repair_pricing_schedule import (
    EXCLUDED_PRICING_CANONICALS,
    HARD_AVOID_PRICING_CANONICALS,
    apply_quote_response,
    canonical_pricing_candidates,
    dictionary_pricing_candidates,
    needs_pricing,
    next_request_id,
    parse_quote_response,
    pricing_row_from_quote,
    is_hard_avoid_pricing_candidate,
    suggest_pricing_method,
    suggest_supplier_type,
)


def test_reviewed_pricing_candidate_is_included_with_dictionary_candidates() -> None:
    decisions = pd.DataFrame(
        [
            {
                "repair_key": "seat torn",
                "repair_item": "seat torn.",
                "decision": "Add dictionary rule",
                "target_category": "interior",
                "canonical_defect": "seat_damage",
            },
            {
                "repair_key": "and",
                "repair_item": "and.",
                "decision": "Ignore as boilerplate",
                "target_category": "boilerplate",
                "canonical_defect": "boilerplate_joiner_noise",
            },
        ]
    )

    candidates = canonical_pricing_candidates(decisions)

    row = candidates[candidates["canonical_defect"] == "seat_damage"].iloc[0]
    assert row["category"] == "interior"
    assert "boilerplate_joiner_noise" not in set(candidates["canonical_defect"])


def test_needs_pricing_excludes_items_already_in_schedule() -> None:
    candidates = pd.DataFrame(
        [
            {"canonical_defect": "battery_issue", "category": "replacement", "examples": "", "decision_count": 2},
            {"canonical_defect": "windscreen_damage", "category": "glass", "examples": "", "decision_count": 1},
        ]
    )
    schedule = pd.DataFrame([{"canonical_defect": "battery_issue"}])

    missing = needs_pricing(candidates, schedule)

    assert missing["canonical_defect"].tolist() == ["windscreen_damage"]


def test_dictionary_pricing_candidates_include_existing_repair_dictionary_items() -> None:
    candidates = dictionary_pricing_candidates()

    assert "windscreen_damage" in set(candidates["canonical_defect"])
    assert "boilerplate_feature_list" not in set(candidates["canonical_defect"])
    assert "body_location_list" not in set(candidates["canonical_defect"])


def test_supplier_suggestions_distinguish_wreckers_from_specialists() -> None:
    assert suggest_pricing_method("mirror_light_damage") == "wrecker_part_price"
    assert suggest_supplier_type("mirror_light_damage") == "wrecker"
    assert suggest_supplier_type("battery_issue") == "tyre_battery"
    assert suggest_pricing_method("windscreen_damage") == "repair_quote"
    assert suggest_supplier_type("windscreen_damage") == "glass"


def test_hard_avoid_items_are_excluded_from_pricing_candidates() -> None:
    decisions = pd.DataFrame(
        [
            {
                "repair_key": "engine light on",
                "repair_item": "engine light on.",
                "decision": "Add dictionary rule",
                "target_category": "mechanical",
                "canonical_defect": "engine_light_on",
            },
            {
                "repair_key": "windscreen cracked",
                "repair_item": "windscreen cracked.",
                "decision": "Add dictionary rule",
                "target_category": "glass",
                "canonical_defect": "windscreen_damage",
            },
        ]
    )

    candidates = canonical_pricing_candidates(decisions)

    assert "engine_light_on" not in set(candidates["canonical_defect"])
    assert "windscreen_damage" in set(candidates["canonical_defect"])


def test_non_priceable_catch_all_items_are_excluded_from_pricing_candidates() -> None:
    decisions = pd.DataFrame(
        [
            {
                "repair_key": "gear knob missing",
                "repair_item": "gear knob missing.",
                "decision": "Add dictionary rule",
                "target_category": "replacement",
                "canonical_defect": "replacement_required",
            },
            {
                "repair_key": "front bumper",
                "repair_item": "front bumper.",
                "decision": "Add dictionary rule",
                "target_category": "cosmetic",
                "canonical_defect": "body_location_list",
            },
            {
                "repair_key": "sunroof cracked",
                "repair_item": "sunroof cracked.",
                "decision": "Add dictionary rule",
                "target_category": "replacement",
                "canonical_defect": "sunroof_damage",
            },
        ]
    )

    candidates = canonical_pricing_candidates(decisions)

    assert "replacement_required" not in set(candidates["canonical_defect"])
    assert "body_location_list" not in set(candidates["canonical_defect"])
    assert "sunroof_damage" in set(candidates["canonical_defect"])


def test_hard_avoid_exclusion_set_covers_common_avoid_canonicals() -> None:
    expected = {
        "engine_oil_leak",
        "transmission_requires_attention",
        "tow_or_no_drive_required",
        "structural_damage",
        "engine_smoke_visible",
        "engine_idling_rough",
        "head_gasket_issue",
        "brakes_require_attention",
        "steering_requires_attention",
    }

    assert expected.issubset(HARD_AVOID_PRICING_CANONICALS)


def test_non_priceable_exclusion_set_covers_helper_and_catch_all_canonicals() -> None:
    assert {"replacement_required", "body_location_list"}.issubset(EXCLUDED_PRICING_CANONICALS)


def test_hard_avoid_keyword_filter_catches_combined_review_keys() -> None:
    assert is_hard_avoid_pricing_candidate(
        "engine_fluid_leak_large_scuff_on_front_bumper_medium_scratch"
    )
    assert is_hard_avoid_pricing_candidate("medium_dent_on_top_of_left_front_door_frame")
    assert not is_hard_avoid_pricing_candidate("paint_damage")


def test_next_request_id_increments_existing_ids() -> None:
    existing = pd.DataFrame([{"request_id": "RQ-0003"}, {"request_id": "manual"}])

    assert next_request_id(existing) == "RQ-0004"


def test_parse_quote_response_extracts_range_and_typical_price() -> None:
    parsed = parse_quote_response("Low end is $220, high is $480. Most jobs are usually $320.")

    assert parsed["quoted_low"] == 220
    assert parsed["quoted_high"] == 480
    assert parsed["quoted_default"] == 320
    assert parsed["response_parse_status"] == "parsed_price"


def test_parse_quote_response_extracts_shorthand_money_ranges() -> None:
    parsed = parse_quote_response("Cost varies from $400-500, or total $550-700 as a rough guide.")

    assert parsed["quoted_low"] == 400
    assert parsed["quoted_high"] == 700


def test_apply_quote_response_and_promote_to_pricing_row() -> None:
    quotes = pd.DataFrame(
        [
            {
                "request_id": "RQ-0099",
                "canonical_defect": "seat_damage",
                "category": "interior",
                "vehicle_class": "small_hatch",
                "supplier": "Example Upholstery",
                "recipient_email": "quotes@example.com",
                "status": "sent",
                "request_date": "2026-06-27",
                "notes": "cloth seat repair",
            }
        ]
    )

    updated = apply_quote_response(
        quotes,
        "RQ-0099",
        "This would be $180 to $350 depending on fabric. Typical is $250.",
        response_date="2026-06-28",
    )
    pricing = pricing_row_from_quote(updated, "RQ-0099")

    row = updated.iloc[0]
    assert row["status"] == "replied"
    assert row["quoted_low"] == 180
    assert row["quoted_high"] == 350
    assert row["quoted_default"] == 250
    assert pricing is not None
    assert pricing["canonical_defect"] == "seat_damage"
    assert pricing["default_estimate"] == 250
