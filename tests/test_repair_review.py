import pandas as pd

from shared.repair_review import append_unclassified_condition_lines, repair_mapping_summary


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


def test_append_unclassified_condition_lines_writes_live_queue_rows(tmp_path) -> None:
    queue_path = tmp_path / "repair_review_live_queue.csv"

    appended = append_unclassified_condition_lines(
        ["sunglasses holder requires attention", "  "],
        vehicle="2013 HYUNDAI I30 active petrol",
        url="https://example.com/listing",
        condition_notes="condition notes",
        path=queue_path,
    )

    assert appended == 1
    out = pd.read_csv(queue_path).fillna("")
    assert len(out) == 1
    row = out.iloc[0]
    assert row["repair_key"] == "sunglasses holder requires attention"
    assert row["repair_item"] == "sunglasses holder requires attention"
    assert row["review_bucket"] == "Needs AI Analysis review"
    assert row["status"] == "unclassified"
    assert row["category"] == "unclassified"
    assert row["example_vehicles"] == "2013 HYUNDAI I30 active petrol"


def test_append_unclassified_condition_lines_dedupes_by_repair_key(tmp_path) -> None:
    queue_path = tmp_path / "repair_review_live_queue.csv"

    append_unclassified_condition_lines(
        ["Sunglasses Holder Requires Attention"],
        vehicle="old example",
        url="https://example.com/old",
        condition_notes="old notes",
        path=queue_path,
    )
    append_unclassified_condition_lines(
        ["sunglasses holder requires attention"],
        vehicle="new example",
        url="https://example.com/new",
        condition_notes="new notes",
        path=queue_path,
    )

    out = pd.read_csv(queue_path).fillna("")
    assert len(out) == 1
    assert out.iloc[0]["example_vehicles"] == "new example"
    assert out.iloc[0]["example_urls"] == "https://example.com/new"
