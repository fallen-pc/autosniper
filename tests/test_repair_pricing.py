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


def test_repair_fragments_preserve_split_items_and_unclassified_status() -> None:
    assessment = assess_repairs("dents or marks on body consistent with age. bull bar.")
    records = repair_fragments_to_records(assessment)

    assert [record["original_text"] for record in records] == [
        "dents or marks on body consistent with age.",
        "bull bar.",
    ]
    assert records[0]["status"] == "matched"
    assert records[1]["status"] == "unclassified"


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
