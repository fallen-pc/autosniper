from __future__ import annotations

import re

import pytest

from shared import condition_normalizer as cn


def test_normalize_text_expands_abbreviations_and_collapses_whitespace() -> None:
    assert cn.normalize_text("  LHF   Guard  SCRATCHED\r\n") == "left hand front guard scratched"
    assert cn.normalize_text("RHS door, ODO faulty") == "right hand side door, odometer faulty"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_normalize_text_blank_inputs(value) -> None:
    assert cn.normalize_text(value) == ""


def test_normalize_text_normalizes_unicode() -> None:
    assert cn.normalize_text("ＬＨＦ guard") == "left hand front guard"


def test_tokenize_splits_alphanumerics_only() -> None:
    assert cn.tokenize("Left-hand front guard 2x") == ["left", "hand", "front", "guard", "2x"]
    assert cn.tokenize("") == []


def test_contains_multiple_defect_heads() -> None:
    assert cn._contains_multiple_defect_heads("bumper scratched and dented") is True
    assert cn._contains_multiple_defect_heads("bumper scratched") is False
    # Paint/fade wording alone is treated as a single defect head.
    assert cn._contains_multiple_defect_heads("paint fading") is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 1),
        ("bonnet dented", 1),
        ("taillights broken", 2),
        ("both seats torn", 2),
        ("front and rear bar damage", 2),
        ("numerous panels dented", 3),
    ],
)
def test_estimate_component_count(text, expected) -> None:
    assert cn.estimate_component_count(text) == expected


def test_split_defect_lines_empty_input() -> None:
    assert cn.split_defect_lines("") == []


def test_split_defect_lines_uses_v2_rules_when_available() -> None:
    lines = cn.split_defect_lines("Medium dents, marks, scratches on body panels; windscreen cracked")

    assert lines == ["medium dent and marks", "scratches on body panels", "windscreen cracked"]


def test_split_defect_lines_v1_fallback_splits_conjunctions(monkeypatch) -> None:
    monkeypatch.setattr(cn, "_load_split_rules_v2", lambda: {})

    lines = cn.split_defect_lines("Front bumper scratched and dented; windscreen cracked")

    assert lines == ["Front bumper scratched", "dented", "windscreen cracked"]


def test_split_defect_lines_v1_fallback_merges_location_only_fragments(monkeypatch) -> None:
    monkeypatch.setattr(cn, "_load_split_rules_v2", lambda: {})

    lines = cn.split_defect_lines("Guard dented\nrear left")

    assert lines == ["Guard dented and rear left"]


def test_split_with_v2_rules_applies_synonyms_and_cleanup() -> None:
    rules = {
        "splitters": [";"],
        "regex_rules": [{"pattern": "ignored", "action": "keep"}],
        "synonyms": {"windshield": "windscreen"},
        "remove_words": ["the"],
        "cleanup": {"lowercase": True, "strip_punctuation": True, "trim_whitespace": True},
    }

    assert cn._split_with_v2_rules("The Windshield CRACKED; Bonnet dented!", rules) == [
        "windscreen cracked",
        "bonnet dented",
    ]


def test_split_with_v2_rules_ignores_invalid_regex_rules() -> None:
    rules = {"splitters": [], "regex_rules": [{"pattern": "(unclosed", "action": "split"}]}

    assert cn._split_with_v2_rules("bonnet dented", rules) == ["bonnet dented"]


def test_load_rules_parses_csv_and_sorts_by_priority(tmp_path) -> None:
    rules_path = tmp_path / "rules.csv"
    rules_path.write_text(
        "rule_id,pattern,category,severity,priority\n"
        "low_priority,dent,body,0,50\n"
        "high_priority,crack,glass,yes,10\n"
        "bad_priority,rust,body,1,not-a-number\n"
        "incomplete,,body,1,5\n",
        encoding="utf-8",
    )

    rules = cn._load_rules(rules_path)

    assert [rule.rule_id for rule in rules] == ["high_priority", "low_priority", "bad_priority"]
    assert rules[0].severity is True
    assert rules[1].severity is False
    assert rules[2].priority == 100
    assert rules[0].pattern.search("CRACKED windscreen")


def test_load_rules_returns_empty_for_missing_file(tmp_path) -> None:
    assert cn._load_rules(tmp_path / "missing.csv") == []


def test_load_rules_public_wrapper_reads_repo_config() -> None:
    assert cn.load_rules(), "expected the bundled v1 rules file to contain rules"


def test_map_categories_v2_dictionary_wins_when_it_matches() -> None:
    matched, severity, trace = cn.map_categories("windscreen cracked", cn.tokenize("windscreen cracked"))

    assert matched == ["glass"]
    assert severity is True
    assert trace


def test_map_categories_falls_back_to_v1_rules(monkeypatch) -> None:
    monkeypatch.setattr(cn, "_load_v2_dictionary", lambda: [])
    rules = [
        cn.Rule(rule_id="r_dent", pattern=re.compile("dent", re.IGNORECASE), category="body", severity=False, priority=1),
        cn.Rule(rule_id="r_rust", pattern=re.compile("rust", re.IGNORECASE), category="body", severity=True, priority=2),
        cn.Rule(rule_id="r_glass", pattern=re.compile("crack", re.IGNORECASE), category="glass", severity=False, priority=3),
    ]

    matched, severity, trace = cn.map_categories("dented, rusty rust and cracked", [], rules=rules)

    assert matched == ["body", "glass"]
    assert severity is True
    assert trace == ["r_dent", "r_rust", "r_glass"]


def test_map_categories_unknown_for_blank_or_unmatched(monkeypatch) -> None:
    monkeypatch.setattr(cn, "_load_v2_dictionary", lambda: [])

    assert cn.map_categories("", [], rules=[]) == (["unknown"], False, ["unknown"])
    assert cn.map_categories("pristine", [], rules=[]) == (["unknown"], False, ["unknown"])


def test_map_categories_v2_helper_handles_blank_text() -> None:
    assert cn._map_categories_v2("", []) == (["unknown"], False, ["unknown"])


def test_load_v2_dictionary_builds_entries(monkeypatch, tmp_path) -> None:
    path = tmp_path / "dictionary.yaml"
    path.write_text(
        "entries:\n"
        "  - raw_phrase: bonnet dented\n"
        "    category: body\n"
        "    severity_hint: high\n"
        "  - pattern: 'crack(ed)? windscreen'\n"
        "    canonical_defect: cracked_windscreen\n"
        "    category: glass\n"
        "    severity_hint: low\n"
        "  - raw_phrase: no category\n"
        "  - category: body\n"
        "  - not-a-mapping\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cn, "RULES_V2_PATH", path)

    entries = cn._load_v2_dictionary()

    assert [entry.entry_id for entry in entries] == ["bonnet dented", "cracked_windscreen"]
    assert entries[0].severity is True
    assert entries[1].severity is False
    assert entries[1].pattern.search("CRACKED WINDSCREEN")


@pytest.mark.parametrize("payload", ["entries: not-a-list\n", "just a string\n"])
def test_load_v2_dictionary_rejects_bad_payloads(monkeypatch, tmp_path, payload) -> None:
    path = tmp_path / "dictionary.yaml"
    path.write_text(payload, encoding="utf-8")
    monkeypatch.setattr(cn, "RULES_V2_PATH", path)

    assert cn._load_v2_dictionary() == []


def test_load_v2_dictionary_missing_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cn, "RULES_V2_PATH", tmp_path / "missing.yaml")

    assert cn._load_v2_dictionary() == []


def test_load_split_rules_v2_missing_or_invalid(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cn, "SPLIT_RULES_V2_PATH", tmp_path / "missing.yaml")
    assert cn._load_split_rules_v2() == {}

    path = tmp_path / "split.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    monkeypatch.setattr(cn, "SPLIT_RULES_V2_PATH", path)
    assert cn._load_split_rules_v2() == {}


def test_strip_punctuation_and_apply_synonyms() -> None:
    assert cn._strip_punctuation("bonnet, dented!") == "bonnet  dented "
    assert cn._apply_synonyms("windshield chipped", {"windshield": "windscreen"}) == "windscreen chipped"
