from __future__ import annotations

import os

import pandas as pd

from shared import repair_pricing
from shared.repair_pricing import (
    RepairAssessment,
    apply_repairs_to_max_bid,
    assess_repairs,
    repair_decision_label,
    repair_fragments_to_records,
    split_condition_lines,
    vehicle_class_for_listing,
)


def _write_review_decisions(path, rows) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)
    repair_pricing._review_decision_lookup.cache_clear()


def test_assess_repairs_applies_hard_avoid_review_decision(monkeypatch, tmp_path) -> None:
    decisions_path = tmp_path / "repair_review_decisions.csv"
    _write_review_decisions(
        decisions_path,
        [
            {
                "repair_key": "rough idle",
                "repair_item": "rough idle.",
                "decision": "Add dictionary rule",
                "target_category": "mechanical",
                "canonical_defect": "engine_running_fault",
                "severity_hint": "high",
                "cost_model": "hard_avoid",
                "notes": "operator-approved runtime-effective",
            }
        ],
    )
    monkeypatch.setattr(repair_pricing, "DECISIONS_PATH", decisions_path)

    assessment = assess_repairs("rough idle.")

    assert assessment.hard_avoid is True
    assert assessment.reasons == ["REVIEW_DECISION_AVOID: rough idle."]


def test_review_decision_matches_normalized_condition_punctuation(monkeypatch, tmp_path) -> None:
    decisions_path = tmp_path / "repair_review_decisions.csv"
    _write_review_decisions(
        decisions_path,
        [
            {
                "repair_key": "engine tapping rattling noise",
                "repair_item": "engine tapping rattling noise.",
                "decision": "Add dictionary rule",
                "target_category": "mechanical",
                "canonical_defect": "engine_fault",
                "severity_hint": "high",
                "cost_model": "hard_avoid",
                "notes": "operator-approved runtime-effective",
            }
        ],
    )
    monkeypatch.setattr(repair_pricing, "DECISIONS_PATH", decisions_path)

    assessment = assess_repairs("engine tapping / rattling noise.")

    assert assessment.hard_avoid is True
    assert assessment.reasons == ["REVIEW_DECISION_AVOID: engine tapping / rattling noise."]


def test_assess_repairs_applies_nonmechanical_review_decision(monkeypatch, tmp_path) -> None:
    decisions_path = tmp_path / "repair_review_decisions.csv"
    _write_review_decisions(
        decisions_path,
        [
            {
                "repair_key": "dash screen not working",
                "repair_item": "dash screen not working.",
                "decision": "Add dictionary rule",
                "target_category": "interior",
                "canonical_defect": "control_damage",
                "severity_hint": "medium",
                "cost_model": "fixed_replacement",
                "notes": "operator-approved runtime-effective",
            }
        ],
    )
    monkeypatch.setattr(repair_pricing, "DECISIONS_PATH", decisions_path)

    assessment = assess_repairs("dash screen not working.")
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    assert records[0]["status"] == "matched"
    assert records[0]["canonical_defects"] == "control_damage"


def test_reviewed_context_fragment_overrides_generic_body_location_match(monkeypatch, tmp_path) -> None:
    decisions_path = tmp_path / "repair_review_decisions.csv"
    _write_review_decisions(
        decisions_path,
        [
            {
                "repair_key": "lh rear door",
                "repair_item": "lh rear door.",
                "decision": "Mark context fragment",
                "target_category": "context_fragment",
                "canonical_defect": "body_location_context",
                "severity_hint": "low",
                "cost_model": "no_cost",
                "notes": "operator-approved runtime-effective",
            }
        ],
    )
    monkeypatch.setattr(repair_pricing, "DECISIONS_PATH", decisions_path)

    assessment = assess_repairs("lh rear door.")
    records = repair_fragments_to_records(assessment)

    assert assessment.total_cost == 0
    assert records[0]["status"] == "ignored"
    assert records[0]["canonical_defects"] == "body_location_context"


def test_assess_repairs_glass_case_is_consistent() -> None:
    upper = assess_repairs("Windscreen Chipped or Cracked.")
    lower = assess_repairs("windscreen chipped or cracked.")

    assert upper.hard_avoid is False
    assert lower.hard_avoid is False
    assert upper.pills == ["GLASS"]
    assert lower.pills == ["GLASS"]
    # Windscreen replacement priced from repair_pricing_schedule.csv ($500 default).
    assert upper.base_cost == 500
    assert lower.base_cost == 500
    assert upper.total_cost == 750
    assert lower.total_cost == 750


def test_assess_repairs_prices_tyre_puncture_as_repairable() -> None:
    assessment = assess_repairs(
        "comment: one tyre has a pin in it.",
        vehicle_class="small_hatch",
    )
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    assert records[0]["canonical_defects"] == "tyre_puncture"
    assert records[0]["status"] == "matched"
    assert assessment.replacement_cost == 40
    assert assessment.total_cost_low == 40
    assert assessment.total_cost_high == 40
    assert assessment.pricing_class_uncertain is False


def test_assess_repairs_prices_lamp_damage_and_condensation() -> None:
    assessment = assess_repairs(
        "condensation in left brake light. crack in rear right reversing light."
    )
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    assert all(record["canonical_defects"] == "lighting_condensation_damage" for record in records)
    assert assessment.replacement_cost == 500


def test_assess_repairs_prices_driver_window_not_closing() -> None:
    assessment = assess_repairs("interior: driver window won't close.")
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    assert records[0]["canonical_defects"] == "window_regulator_fault"
    assert assessment.replacement_cost == 500


def test_assess_repairs_unknown_boilerplate_not_double_counted() -> None:
    assessment = assess_repairs(
        "please refer to the photos or arrange inspection to view the condition of this vehicle."
    )

    assert assessment.hard_avoid is False
    assert assessment.pills == ["UNKNOWN"]
    assert assessment.risk_buffer == 300
    assert assessment.base_cost == 300
    assert assessment.total_cost == 300


def test_assess_repairs_detects_replacement_damage_from_v2_patterns() -> None:
    assessment = assess_repairs("front cracked bumper.\ndamaged driver side headlight")

    assert assessment.hard_avoid is False
    assert "PANEL_REPLACE" in assessment.pills
    assert assessment.replacement_cost == 850
    assert assessment.base_cost == 850
    assert assessment.total_cost == 1275


def test_split_condition_lines_splits_punctuated_fragments() -> None:
    lines = split_condition_lines(
        "interior damage: drivers seat slight tear; exterior damage: dent of front bumper bar. "
        "slight scratches on passenger side doors and side step | door handle not working"
    )

    assert lines == [
        "interior damage: drivers seat slight tear.",
        "exterior damage: dent of front bumper bar.",
        "slight scratches on passenger side doors and side step.",
        "door handle not working.",
    ]


def test_split_condition_lines_repairs_glued_grays_section_labels() -> None:
    lines = split_condition_lines(
        "interior: tachometer failing to register intermittently, steering wheel wornexterior: "
        "vehicle stalling at times, brakes require attention, tilt tray recommended for pickup"
    )

    assert lines == [
        "interior: tachometer failing to register intermittently.",
        "steering wheel worn.",
        "exterior: vehicle stalling at times.",
        "brakes require attention.",
        "tilt tray recommended for pickup.",
    ]


def test_split_condition_lines_decodes_nested_html_entities_before_splitting() -> None:
    lines = split_condition_lines(
        "medium scratch on passenger side front &amp;amp;amp;amp;amp; rear guard panels."
    )

    assert lines == ["medium scratch on passenger side front & rear guard panels."]


def test_split_condition_lines_carries_damage_context_to_body_locations() -> None:
    lines = split_condition_lines("medium scratch on roof, bonnet, rear bumper.")

    assert lines == [
        "medium scratch on roof.",
        "medium scratch on bonnet.",
        "medium scratch on rear bumper.",
    ]


def test_split_condition_lines_carries_body_panel_damage_context() -> None:
    lines = split_condition_lines("body/panel damage tailgate, rear bar & left rear tail lamp.")

    assert lines == [
        "body/panel damage tailgate.",
        "body/panel damage rear bar & left rear tail lamp.",
    ]


def test_assess_repairs_counts_mixed_replacement_and_cosmetic_damage() -> None:
    assessment = assess_repairs("front cracked bumper and scratches and dents visible around vehicle")

    assert assessment.hard_avoid is False
    assert {"COSMETIC_PANEL", "PANEL_REPLACE"}.issubset(set(assessment.pills))
    assert assessment.cosmetic_panels == 3
    assert assessment.replacement_cost == 600
    assert assessment.base_cost == 1500
    assert assessment.total_cost == 2250


def test_assess_repairs_does_not_add_cosmetic_panel_for_single_replacement_item() -> None:
    assessment = assess_repairs("damaged driver side headlight")

    assert assessment.hard_avoid is False
    assert assessment.pills == ["PANEL_REPLACE"]
    assert assessment.cosmetic_panels == 0
    assert assessment.replacement_cost == 250
    assert assessment.base_cost == 250


def test_assess_repairs_does_not_treat_interior_damage_as_body_panel() -> None:
    assessment = assess_repairs(
        "interior damage: drivers seat slight tear.",
        vehicle_class="small_hatch",
    )

    assert assessment.hard_avoid is False
    assert assessment.pills == []
    assert assessment.cosmetic_panels == 0
    # seat_damage priced from the schedule's direct supplier quote ($500).
    assert assessment.replacement_cost == 500
    assert assessment.base_cost == 500


def test_assess_repairs_caps_unknown_photo_risk_after_fragment_split() -> None:
    assessment = assess_repairs("please refer to the photos; arrange inspection to view vehicle condition.")

    assert assessment.hard_avoid is False
    assert assessment.pills == ["UNKNOWN"]
    assert assessment.risk_buffer == 300
    assert assessment.base_cost == 300


def test_assess_repairs_mechanical_hard_avoid_uses_mechanical_bucket() -> None:
    assessment = assess_repairs("engine noise observed.")

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "mechanical"
    assert assessment.pills == ["MECHANICAL"]
    assert assessment.base_cost == 10000
    assert assessment.total_cost == 10000


def test_assess_repairs_bare_engine_light_is_hard_avoid() -> None:
    assessment = assess_repairs("scratches and dents visible around vehicle, engine light, door trim missing")

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "mechanical"
    assert assessment.pills == ["MECHANICAL"]
    assert assessment.total_cost == 10000


def test_assess_repairs_head_gasket_language_is_hard_avoid() -> None:
    assessment = assess_repairs(
        "engine cooling system requires attention. suspect head gasket failure causing over pressurization."
    )

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "mechanical"
    assert assessment.pills == ["MECHANICAL"]
    assert assessment.total_cost == 10000


def test_assess_repairs_engine_requires_attention_is_mechanical_hard_avoid() -> None:
    for text in (
        "engine requires attention.",
        "engine needs attention dents or marks on body.",
        "engine issues.",
        "engine tick.",
        "paint peeling around the car engine ticking noise observed.",
        "motor requires attention.",
    ):
        assessment = assess_repairs(text)
        assert assessment.hard_avoid is True, text
        assert assessment.hard_avoid_reason == "mechanical", text


def test_assess_repairs_smoke_language_is_mechanical_hard_avoid() -> None:
    for text in (
        "black smoke evident.",
        "exhaust smoke.",
        "smoke from exhaust paint peeling driver side rear quarter panel.",
        "blowing smoke.",
    ):
        assessment = assess_repairs(text)
        assert assessment.hard_avoid is True, text
        assert assessment.hard_avoid_reason == "mechanical", text


def test_assess_repairs_driveline_gearbox_coolant_faults_are_mechanical_hard_avoid() -> None:
    for text in (
        "driveline requires attention.",
        "gearbox shudder.",
        "coolant issue.",
        "steering requires attention.",
        "noise whilst driving/steering.",
    ):
        assessment = assess_repairs(text)
        assert assessment.hard_avoid is True, text
        assert assessment.hard_avoid_reason == "mechanical", text


def test_assess_repairs_steering_wheel_wear_is_not_mechanical() -> None:
    for text in (
        "steering wheel worn.",
        "interior: steering wheel requires attention.",
    ):
        assessment = assess_repairs(text)
        assert assessment.hard_avoid is False, text


def test_assess_repairs_feature_list_with_airbags_is_not_warning_light_avoid() -> None:
    # Regression: the v2 warning_light pattern used to match bare "on" inside
    # words like "front"/"control", hard-avoiding plain equipment lists.
    for text in (
        "dual front airbags second row windows.",
        "abs brakes power windows air conditioning.",
        "air conditioning cd player central locking driver airbag electric windows park distance control.",
    ):
        assessment = assess_repairs(text)
        assert assessment.hard_avoid is False, text


def test_assess_repairs_warning_light_on_still_hard_avoids() -> None:
    for text in (
        "airbag warning light on.",
        "abs light on.",
        "tyre pressure warning light on.",
    ):
        assessment = assess_repairs(text)
        assert assessment.hard_avoid is True, text
        assert assessment.hard_avoid_reason == "mechanical", text


def test_assess_repairs_pillar_trim_is_not_structural_hard_avoid() -> None:
    assessment = assess_repairs("drivers side a pillar trim requires attention.")

    assert assessment.hard_avoid is False


def test_assess_repairs_pillar_damage_still_structural_hard_avoid() -> None:
    assessment = assess_repairs("medium dent on passenger a pillar.")

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "structural"


def test_assess_repairs_structural_hard_avoid_uses_structural_bucket() -> None:
    assessment = assess_repairs("structural damage on chassis rail.")

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "structural"
    assert assessment.pills == ["STRUCTURAL"]
    assert assessment.base_cost == 8000
    assert assessment.total_cost == 8000


def test_assess_repairs_does_not_treat_roof_rail_feature_as_structural() -> None:
    assessment = assess_repairs("air conditioning | roof rail | electric windows")

    assert assessment.hard_avoid is False
    assert assessment.total_cost == 0
    assert all(fragment.hard_avoid_reason is None for fragment in assessment.fragments)


def test_assess_repairs_engine_idling_rough_is_mechanical_hard_avoid() -> None:
    assessment = assess_repairs("engine idling rough")

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "mechanical"
    assert assessment.total_cost == 10000
    assert repair_decision_label(assessment) == "HARD AVOID (mechanical)"


def test_assess_repairs_no_drive_tilt_tray_is_mechanical_hard_avoid() -> None:
    assessment = assess_repairs("vehicle cannot be driven off site, tilt tray truck pick up is required.")

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "mechanical"


def test_assess_repairs_stalling_brakes_tilt_tray_recommended_is_mechanical_hard_avoid() -> None:
    assessment = assess_repairs(
        "interior: tachometer failing to register intermittently, steering wheel wornexterior: "
        "vehicle stalling at times, brakes require attention, tilt tray recommended for pickup"
    )

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "mechanical"
    assert assessment.total_cost == 10000
    hard_fragments = [fragment for fragment in assessment.fragments if fragment.status == "hard_avoid"]
    assert [fragment.original_text for fragment in hard_fragments] == ["exterior: vehicle stalling at times."]


def test_assess_repairs_reversed_mirror_damage_is_replacement() -> None:
    assessment = assess_repairs("service history digital, cracked passenger side mirror")

    assert assessment.hard_avoid is False
    assert "PANEL_REPLACE" in assessment.pills
    assert assessment.replacement_cost == 250


def test_assess_repairs_door_handle_not_working_is_replacement() -> None:
    assessment = assess_repairs("door handle not working or broken.")

    assert assessment.hard_avoid is False
    assert "PANEL_REPLACE" in assessment.pills
    assert assessment.replacement_cost == 250


def test_assess_repairs_classifies_worn_door_card_carpet_and_headlining() -> None:
    assessment = assess_repairs("door card worn. carpet worn in places. hood lining sagging.")
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    assert assessment.total_cost == 750
    assert [record["status"] for record in records] == ["matched", "matched", "matched"]
    assert all(record["category"] == "interior" for record in records)


def test_assess_repairs_classifies_visible_corrosion_as_body_condition_cost() -> None:
    assessment = assess_repairs("corrosion visible back left panel below light.")
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    # Corrosion is body-shop work priced from the schedule quote ($1,200), not a
    # $300 cosmetic panel, and it uses the with_replacement cap tier.
    assert "PANEL_REPLACE" in assessment.pills
    assert assessment.total_cost == 1200
    assert records[0]["canonical_defects"] == "body_location_list|corrosion_damage"


def test_assess_repairs_ignores_grays_metadata_and_ppsr_boilerplate() -> None:
    assessment = assess_repairs(
        "Key: Yes. Engine Turns Over: Yes. Owners Manual: No. "
        "Please allow up to 10 business days for the security interest registration to be removed."
    )
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    assert assessment.total_cost == 0
    assert {record["status"] for record in records} == {"ignored"}
    assert all(record["category"] == "boilerplate" for record in records)


def test_assess_repairs_classifies_dash_radio_and_corrosion_evident() -> None:
    assessment = assess_repairs("dash torn or cracked. radio not working. corrosion evident.")
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    # interior_trim $250 + control_damage $900 (schedule quote) + corrosion $1,200
    # = $2,350, capped at with_replacement $1,500, x1.5 moderate severity.
    assert assessment.total_cost == 2250
    assert [record["category"] for record in records] == ["interior", "interior", "cosmetic"]
    assert records[0]["canonical_defects"] == "interior_trim_damage"
    assert records[1]["canonical_defects"] == "control_damage"
    assert records[2]["canonical_defects"] == "corrosion_damage"


def test_assess_repairs_classifies_audit_gap_repairs() -> None:
    assessment = assess_repairs(
        "cracked windscreen. hazed headlights. fuel flap broken. sunroof requires attention."
    )
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    assert [record["category"] for record in records] == ["glass", "replacement", "replacement", "replacement"]
    assert records[0]["canonical_defects"] == "windscreen_damage"
    assert records[1]["canonical_defects"] == "lighting_damage"
    assert records[2]["canonical_defects"] == "fuel_flap_damage"
    assert records[3]["canonical_defects"] == "sunroof_damage"


def test_assess_repairs_ignores_salvage_and_usage_risk_boilerplate() -> None:
    assessment = assess_repairs(
        "Mine Site Vehicle. This vehicle is sold in a SALVAGE AUCTION. "
        "Grays strongly recommends a mechanical inspection be completed prior to bidding."
    )
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    assert assessment.total_cost == 0
    assert {record["status"] for record in records} == {"ignored"}
    assert all(record["category"] == "boilerplate" for record in records)


def test_assess_repairs_ignores_safety_removal_and_feature_boilerplate() -> None:
    assessment = assess_repairs(
        "and. This vehicle is sold in aSALVAGE AUCTION. "
        "Confirmation of Public Liability Certificate of Currency. hill holder system. alloy wheels."
    )
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    assert assessment.total_cost == 0
    assert {record["status"] for record in records} == {"ignored"}
    assert all(record["category"] == "boilerplate" for record in records)


def test_assess_repairs_classifies_wear_and_tear_body_text_as_cosmetic() -> None:
    assessment = assess_repairs("wear and tear consistent with age and kilometres.")
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    assert assessment.total_cost == 300
    assert records[0]["status"] == "matched"
    assert records[0]["category"] == "cosmetic"


def test_assess_repairs_classifies_control_and_attention_gap_repairs() -> None:
    assessment = assess_repairs(
        "sat nav not working. passenger side mirror requires attention. "
        "handbrake requires attention. rooflining requires attention."
    )
    records = repair_fragments_to_records(assessment)

    assert assessment.hard_avoid is False
    assert [record["category"] for record in records] == [
        "interior",
        "replacement",
        "replacement",
        "interior",
    ]
    assert records[0]["canonical_defects"] == "control_damage"
    assert records[1]["canonical_defects"] == "mirror_light_damage"
    assert records[2]["canonical_defects"] == "replacement_required"
    assert records[3]["canonical_defects"] == "interior_trim_damage"


def test_assess_repairs_classifies_pickles_condition_detail_rows() -> None:
    assessment = assess_repairs(
        "Tyre (Spare) missing. Wheel (Spare) missing. "
        "Windscreen (Front) minor pitting visible. Battery Std Light Commercial flat."
    )
    records = repair_fragments_to_records(assessment)
    defects = {record["canonical_defects"] for record in records}

    assert assessment.hard_avoid is False
    assert "PANEL_REPLACE" in assessment.pills
    assert "GLASS" in assessment.pills
    assert "tyre_replacement" in defects
    assert "wheel_missing" in defects
    assert "windscreen_damage" in defects
    assert "battery_issue" in defects


def test_assess_repairs_pickles_mechanical_issue_is_hard_avoid() -> None:
    assessment = assess_repairs("Mechanical mechanical issue - requires attention.")

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "mechanical"
    assert assessment.pills == ["MECHANICAL"]


def test_assess_repairs_pickles_chassis_corrosion_is_structural_hard_avoid() -> None:
    assessment = assess_repairs("Chassis/Undercarriage bubbling/delamination corrosion evident.")

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "structural"
    assert assessment.pills == ["STRUCTURAL"]


def test_assess_repairs_prices_control_damage_from_schedule_quote() -> None:
    assessment = assess_repairs("sat nav not working.", vehicle_class="small_hatch")

    assert assessment.hard_avoid is False
    # Schedule carries a direct supplier quote of $900 for control/infotainment
    # repair, overriding the old hardcoded $250.
    assert assessment.replacement_cost == 900


def test_assess_repairs_hail_damage_bypasses_replacement_cap() -> None:
    assessment = assess_repairs("hail damage visible around vehicle.", vehicle_class="small_hatch")

    assert assessment.hard_avoid is False
    assert "PANEL_REPLACE" in assessment.pills
    # Hail: $1,000 schedule default + 3 panels x $300, exempt from the $1,500
    # with_replacement cap that used to flatten it.
    assert assessment.base_cost == 1900
    assert assessment.total_cost >= 1900


def test_assess_repairs_adas_windscreen_adds_recalibration_premium() -> None:
    standard = assess_repairs("windscreen cracked.")
    adas = assess_repairs("windscreen cracked.", adas_windscreen=True)

    assert standard.glass_cost == 500
    assert adas.glass_cost == 650


def test_repair_fragments_preserve_split_items_and_unclassified_status() -> None:
    assessment = assess_repairs("dents or marks on body consistent with age. bull bar.")
    records = repair_fragments_to_records(assessment)

    assert [record["original_text"] for record in records] == [
        "dents or marks on body consistent with age.",
        "bull bar.",
    ]
    assert records[0]["status"] == "matched"
    assert records[1]["status"] == "unclassified"


def test_numbered_grays_condition_rows_do_not_emit_number_only_fragments() -> None:
    assessment = assess_repairs(
        "1. Rear End (Rear Bar) - Scratched;Dent(s) under 5cm\n"
        "2. Front End (Front Bar) - Scratched\n"
        "Scratches And Dents Visible Around Vehicle"
    )
    records = repair_fragments_to_records(assessment)

    assert all(record["repair_key"] not in {"1", "2"} for record in records)
    assert any(record["repair_key"] == "rear end rear bar scratched" for record in records)
    assert any(record["repair_key"] == "front end front bar scratched" for record in records)


def test_assess_repairs_does_not_price_bare_body_location_without_context(
    monkeypatch, tmp_path
) -> None:
    decisions_path = tmp_path / "repair_review_decisions.csv"
    _write_review_decisions(decisions_path, [])
    monkeypatch.setattr(repair_pricing, "DECISIONS_PATH", decisions_path)

    assessment = assess_repairs("roof.")
    records = repair_fragments_to_records(assessment)

    assert assessment.total_cost == 0
    assert records[0]["status"] == "unclassified"


def test_vehicle_class_mapping_is_shared_for_listing_body_types() -> None:
    assert vehicle_class_for_listing({"body_type": "Hatchback"}) == "small_hatch"
    assert vehicle_class_for_listing({"body_type": "Sedan"}) == "small_sedan"
    assert vehicle_class_for_listing({"body_type": "SUV"}) == "medium_suv"
    assert vehicle_class_for_listing({"body_type": "Wagon"}) == ""
    assert vehicle_class_for_listing({"body_type": "Dual Cab Ute"}) == "ute"
    assert vehicle_class_for_listing({"body_type": "People Mover"}) == "van"
    assert vehicle_class_for_listing({"vehicle_class": "large_suv", "body_type": "Wagon"}) == "large_suv"


def test_class_specific_schedule_band_wins_and_incompatible_class_fails_closed() -> None:
    hatch = assess_repairs("sat nav not working.", vehicle_class="small_hatch")
    suv = assess_repairs("sat nav not working.", vehicle_class="medium_suv")

    assert (hatch.total_cost_low, hatch.total_cost, hatch.total_cost_high) == (600, 900, 1200)
    assert hatch.pricing_class_uncertain is False
    assert suv.replacement_cost == 250
    assert suv.pricing_class_uncertain is True
    assert suv.pricing_incompatible_canonicals == ["control_damage"]
    assert repair_decision_label(suv) == "REVIEW (repair pricing evidence)"


def test_generic_schedule_band_is_valid_for_every_vehicle_class() -> None:
    assessment = assess_repairs("windscreen cracked.", vehicle_class="medium_suv")

    assert (assessment.total_cost_low, assessment.total_cost, assessment.total_cost_high) == (450, 750, 1500)
    assert assessment.pricing_class_uncertain is False


def test_schedule_loader_reloads_when_file_changes(monkeypatch, tmp_path) -> None:
    schedule_path = tmp_path / "repair_pricing_schedule.csv"
    columns = [
        "canonical_defect",
        "vehicle_class",
        "pricing_method",
        "default_estimate",
        "low_estimate",
        "high_estimate",
    ]
    pd.DataFrame(
        [["control_damage", "small_hatch", "repair_quote", 600, 400, 800]],
        columns=columns,
    ).to_csv(schedule_path, index=False)
    original_stat = schedule_path.stat()
    monkeypatch.setattr(repair_pricing, "REPAIR_PRICING_SCHEDULE_PATH", schedule_path)
    repair_pricing._load_schedule_cost_bands.cache_clear()

    first = assess_repairs("sat nav not working.", vehicle_class="small_hatch")
    pd.DataFrame(
        [["control_damage", "small_hatch", "repair_quote", 700, 500, 900]],
        columns=columns,
    ).to_csv(schedule_path, index=False)
    os.utime(schedule_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    second = assess_repairs("sat nav not working.", vehicle_class="small_hatch")

    assert first.replacement_cost == 600
    assert second.replacement_cost == 700
    assert second.total_cost_high == 900


def test_specific_panels_suppress_duplicate_around_vehicle_summary() -> None:
    assessment = assess_repairs(
        "Rear quarter panel dent(s) under 5cm. Front guard dent(s) under 5cm. "
        "Scratches and dents visible around vehicle.",
        vehicle_class="small_hatch",
        vehicle_value=18_380,
    )

    duplicate_fragments = [fragment for fragment in assessment.fragments if fragment.category == "duplicate_summary"]
    assert assessment.cosmetic_panels == 2
    assert len(duplicate_fragments) == 1
    assert duplicate_fragments[0].status == "ignored"


def test_glued_engine_sound_is_split_and_hard_avoided() -> None:
    assessment = assess_repairs(
        "paint peeling on various panelsunusual sound from engine bay when on",
        vehicle_class="small_sedan",
    )

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "mechanical"
    assert any("unusual sound from engine" in line.lower() for line in split_condition_lines(assessment.original_text))


def test_apply_repairs_to_max_bid_keeps_moderate_repairs_marginal() -> None:
    assessment = RepairAssessment(
        hard_avoid=False,
        pills=["COSMETIC_PANEL", "PANEL_REPLACE"],
        cosmetic_panels=2,
        glass_cost=0,
        replacement_cost=850,
        risk_buffer=0,
        base_cost=1500,
        severity_level="moderate",
        severity_multiplier=1.5,
        total_cost=2250,
        reasons=["test repair"],
    )

    adjusted_bid, verdict = apply_repairs_to_max_bid(5000, assessment)

    assert adjusted_bid == 2750
    assert verdict == "Marginal"


def test_apply_repairs_to_max_bid_marks_only_heavier_repairs_not_viable() -> None:
    assessment = RepairAssessment(
        hard_avoid=False,
        pills=["PANEL_REPLACE"],
        cosmetic_panels=3,
        glass_cost=0,
        replacement_cost=1500,
        risk_buffer=300,
        base_cost=2600,
        severity_level="moderate",
        severity_multiplier=1.25,
        total_cost=3250,
        reasons=["test repair"],
    )

    adjusted_bid, verdict = apply_repairs_to_max_bid(6000, assessment)

    assert adjusted_bid == 2750
    assert verdict == "Not Viable"
