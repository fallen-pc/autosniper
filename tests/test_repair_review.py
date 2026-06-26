import pandas as pd

from shared.repair_review import repair_mapping_summary


def test_repair_mapping_passes_when_parser_classifies_every_fragment() -> None:
    records = [
        {
            "repair_key": "engine light on",
            "original_text": "engine light on.",
            "status": "hard_avoid",
            "category": "mechanical",
            "canonical_defects": "warning_light",
        }
    ]

    summary = repair_mapping_summary(records, pd.DataFrame())

    assert summary["pass"] is True
    assert summary["mapped_count"] == 1
    assert summary["needs_review_count"] == 0


def test_repair_mapping_needs_review_for_unknown_fragment_without_decision() -> None:
    records = [
        {
            "repair_key": "new weird repair",
            "original_text": "new weird repair.",
            "status": "unclassified",
            "category": "unclassified",
            "canonical_defects": "",
        }
    ]

    summary = repair_mapping_summary(records, pd.DataFrame())

    assert summary["pass"] is False
    assert summary["needs_review_count"] == 1


def test_repair_mapping_uses_saved_review_decision_as_mapping() -> None:
    records = [
        {
            "repair_key": "new weird repair",
            "original_text": "new weird repair.",
            "status": "unclassified",
            "category": "unclassified",
            "canonical_defects": "",
        }
    ]
    decisions = pd.DataFrame(
        [
            {
                "repair_key": "new weird repair",
                "decision": "Add dictionary rule",
                "target_category": "mechanical",
                "canonical_defect": "new_weird_repair",
            }
        ]
    )

    summary = repair_mapping_summary(records, decisions)

    assert summary["pass"] is True
    assert summary["mapped_count"] == 1
    assert summary["needs_review_count"] == 0


def test_repair_mapping_keeps_leave_unclassified_as_unresolved() -> None:
    records = [
        {
            "repair_key": "vague fragment",
            "original_text": "vague fragment.",
            "status": "unclassified",
            "category": "unclassified",
            "canonical_defects": "",
        }
    ]
    decisions = pd.DataFrame([{"repair_key": "vague fragment", "decision": "Leave unclassified"}])

    summary = repair_mapping_summary(records, decisions)

    assert summary["pass"] is False
    assert summary["needs_review_count"] == 0
    assert summary["unresolved_count"] == 1
