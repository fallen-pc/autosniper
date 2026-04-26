from __future__ import annotations

from shared.repair_pricing import assess_repairs


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
