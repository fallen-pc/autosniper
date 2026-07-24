import pandas as pd

from shared.repair_ai_classifier import AI_SUGGESTION_COLUMNS, classify_repair_review_queue, load_ai_suggestions
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


def test_repair_mapping_does_not_reopen_fragments_after_hard_avoid() -> None:
    records = [
        {
            "repair_key": "later mystery fragment",
            "status": "not_assessed_after_hard_avoid",
            "category": "not_assessed",
            "canonical_defects": "",
        }
    ]

    summary = repair_mapping_summary(records, pd.DataFrame())

    assert summary["pass"] is True
    assert summary["mapped_count"] == 1
    assert summary["needs_review_count"] == 0


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


def test_repair_mapping_matches_normalized_punctuation() -> None:
    records = [
        {
            "repair_key": "rear end (rear bar) - null.",
            "status": "unclassified",
            "category": "unclassified",
            "canonical_defects": "",
        }
    ]
    decisions = pd.DataFrame(
        [
            {
                "repair_key": "rear end rear bar null",
                "repair_item": "rear end rear bar null.",
                "decision": "Mark context fragment",
            }
        ]
    )

    summary = repair_mapping_summary(records, decisions)

    assert summary["pass"] is True
    assert summary["mapped_count"] == 1


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


def test_classify_repair_review_queue_writes_ai_suggestions(tmp_path, monkeypatch) -> None:
    queue_path = tmp_path / "repair_review_live_queue.csv"
    output_path = tmp_path / "repair_review_ai_suggestions.csv"
    pd.DataFrame(
        [
            {
                "repair_key": "sunglasses holder requires attention",
                "repair_item": "sunglasses holder requires attention",
                "status": "unclassified",
                "category": "unclassified",
                "canonical_defects": "",
                "occurrences": 1,
                "listing_count": 1,
                "example_vehicles": "2013 HYUNDAI I30 active petrol",
                "example_condition_notes": "sunglasses holder requires attention",
            }
        ]
    ).to_csv(queue_path, index=False)
    monkeypatch.setenv("OPENAI_API_KEY", "present-but-not-used")

    def fake_caller(rows: pd.DataFrame, *, model: str) -> pd.DataFrame:
        assert model == "test-model"
        assert rows.iloc[0]["repair_key"] == "sunglasses holder requires attention"
        return pd.DataFrame(
            [
                {
                    "repair_key": "sunglasses holder requires attention",
                    "repair_item": "sunglasses holder requires attention",
                    "ai_decision": "Add dictionary rule",
                    "ai_target_category": "interior",
                    "ai_canonical_defect": "interior_trim_damage",
                    "ai_severity_hint": "medium",
                    "ai_cost_model": "fixed_replacement",
                    "ai_confidence": 0.82,
                    "ai_rationale": "Interior storage/trim component needs attention.",
                    "model": model,
                    "suggested_at": "2026-07-21T00:00:00+00:00",
                }
            ],
            columns=AI_SUGGESTION_COLUMNS,
        )

    result = classify_repair_review_queue(
        queue_path=queue_path,
        output_path=output_path,
        model="test-model",
        caller=fake_caller,
    )

    assert result.considered == 1
    assert result.suggested == 1
    suggestions = load_ai_suggestions(output_path)
    assert len(suggestions) == 1
    row = suggestions.iloc[0]
    assert row["ai_decision"] == "Add dictionary rule"
    assert row["ai_target_category"] == "interior"
    assert row["ai_canonical_defect"] == "interior_trim_damage"


def test_classify_repair_review_queue_skips_without_key(tmp_path, monkeypatch) -> None:
    queue_path = tmp_path / "repair_review_live_queue.csv"
    pd.DataFrame(
        [
            {
                "repair_key": "unknown fragment",
                "repair_item": "unknown fragment",
                "status": "unclassified",
                "category": "unclassified",
                "canonical_defects": "",
            }
        ]
    ).to_csv(queue_path, index=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = classify_repair_review_queue(queue_path=queue_path, output_path=tmp_path / "out.csv")

    assert result.considered == 0
    assert result.suggested == 0
    assert result.skipped_reason == "OPENAI_API_KEY missing"


def test_classify_repair_review_queue_fails_closed_on_api_error(tmp_path, monkeypatch) -> None:
    queue_path = tmp_path / "repair_review_live_queue.csv"
    output_path = tmp_path / "out.csv"
    pd.DataFrame(
        [
            {
                "repair_key": "unknown fragment",
                "repair_item": "unknown fragment",
                "status": "unclassified",
                "category": "unclassified",
                "canonical_defects": "",
            }
        ]
    ).to_csv(queue_path, index=False)
    monkeypatch.setenv("OPENAI_API_KEY", "present-but-not-used")

    def failing_caller(rows: pd.DataFrame, *, model: str) -> pd.DataFrame:
        raise RuntimeError("quota exhausted")

    result = classify_repair_review_queue(
        queue_path=queue_path,
        output_path=output_path,
        caller=failing_caller,
    )

    assert result.considered == 1
    assert result.suggested == 0
    assert "quota exhausted" in result.skipped_reason
    assert not output_path.exists()
