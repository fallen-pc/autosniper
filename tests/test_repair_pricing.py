from __future__ import annotations

from shared.repair_pricing import (
    RepairAssessment,
    apply_repairs_to_max_bid,
    assess_repairs,
    repair_decision_label,
    repair_fragments_to_records,
    split_condition_lines,
)


def test_assess_repairs_glass_case_is_consistent() -> None:
    upper = assess_repairs("Windscreen Chipped or Cracked.")
    lower = assess_repairs("windscreen chipped or cracked.")

    assert upper.hard_avoid is False
    assert lower.hard_avoid is False
    assert upper.pills == ["GLASS"]
    assert lower.pills == ["GLASS"]
    assert upper.base_cost == 350
    assert lower.base_cost == 350
    assert upper.total_cost == 525
    assert lower.total_cost == 525


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
    assessment = assess_repairs("interior damage: drivers seat slight tear.")

    assert assessment.hard_avoid is False
    assert assessment.pills == []
    assert assessment.cosmetic_panels == 0
    assert assessment.replacement_cost == 250
    assert assessment.base_cost == 250


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
    assert "COSMETIC_PANEL" in assessment.pills
    assert assessment.total_cost == 300
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
    assert assessment.total_cost == 1200
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


def test_repair_fragments_preserve_split_items_and_unclassified_status() -> None:
    assessment = assess_repairs("dents or marks on body consistent with age. bull bar.")
    records = repair_fragments_to_records(assessment)

    assert [record["original_text"] for record in records] == [
        "dents or marks on body consistent with age.",
        "bull bar.",
    ]
    assert records[0]["status"] == "matched"
    assert records[1]["status"] == "unclassified"


def test_assess_repairs_does_not_price_bare_body_location_without_context() -> None:
    assessment = assess_repairs("roof.")
    records = repair_fragments_to_records(assessment)

    assert assessment.total_cost == 0
    assert records[0]["status"] == "unclassified"


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
