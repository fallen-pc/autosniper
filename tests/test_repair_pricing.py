from __future__ import annotations

from shared.repair_pricing import RepairAssessment, apply_repairs_to_max_bid, assess_repairs


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


def test_assess_repairs_mechanical_hard_avoid_uses_mechanical_bucket() -> None:
    assessment = assess_repairs("engine noise observed.")

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "mechanical"
    assert assessment.pills == ["MECHANICAL"]
    assert assessment.base_cost == 10000
    assert assessment.total_cost == 10000


def test_assess_repairs_structural_hard_avoid_uses_structural_bucket() -> None:
    assessment = assess_repairs("structural damage on chassis rail.")

    assert assessment.hard_avoid is True
    assert assessment.hard_avoid_reason == "structural"
    assert assessment.pills == ["STRUCTURAL"]
    assert assessment.base_cost == 8000
    assert assessment.total_cost == 8000


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
