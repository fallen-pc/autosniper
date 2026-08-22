import pandas as pd

from scripts.build_repair_pricing_matrix import canonicals_needing_price
from shared.repair_pricing_schedule import reviewed_pricing_candidates
from shared.repair_review import latest_repair_decisions
from shared.repair_workbench import (
    dictionary_phrase_rows,
    pricing_coverage_ledger,
    pricing_evidence_status,
    repair_dictionary_nodes,
)


def _decision(**overrides: object) -> dict[str, object]:
    row = {
        "repair_key": "engine light on",
        "repair_item": "engine light on",
        "review_bucket": "Real repair gap",
        "decision": "Add dictionary rule",
        "target_category": "mechanical",
        "canonical_defect": "engine_light_on",
        "severity_hint": "high",
        "cost_model": "hard_avoid",
        "notes": "",
    }
    row.update(overrides)
    return row


def _price(**overrides: object) -> dict[str, object]:
    row = {
        "canonical_defect": "paint_damage",
        "vehicle_class": "small_hatch",
        "pricing_method": "repair_quote",
        "low_estimate": 600,
        "default_estimate": 800,
        "high_estimate": 1000,
        "confidence": "high",
        "evidence_source": "Supplier email",
        "evidence_date": "2026-08-20",
        "notes": "supplied and fitted",
    }
    row.update(overrides)
    return row


def test_latest_repair_decisions_keeps_only_the_last_state_per_key() -> None:
    decisions = pd.DataFrame(
        [
            _decision(canonical_defect="obsolete_engine_rule"),
            _decision(decision="Leave unclassified", canonical_defect=""),
            _decision(repair_key="paint scuff", repair_item="paint scuff", canonical_defect="paint_damage"),
        ]
    )

    current = latest_repair_decisions(decisions)

    assert len(current) == 2
    engine = current[current["repair_key"] == "engine light on"].iloc[0]
    assert engine["decision"] == "Leave unclassified"
    assert engine["canonical_defect"] == ""


def test_dictionary_nodes_count_only_current_active_mappings() -> None:
    decisions = pd.DataFrame(
        [
            _decision(canonical_defect="obsolete_engine_rule"),
            _decision(),
            _decision(repair_key="check engine light", repair_item="check engine light"),
            _decision(
                repair_key="paint scuff",
                repair_item="paint scuff",
                target_category="cosmetic",
                canonical_defect="paint_damage",
                cost_model="cosmetic_panel",
            ),
        ]
    )

    nodes = repair_dictionary_nodes(decisions)

    assert set(nodes["canonical_defect"]) == {"engine_light_on", "paint_damage"}
    engine = nodes[nodes["canonical_defect"] == "engine_light_on"].iloc[0]
    assert engine["phrase_count"] == 2
    assert bool(engine["hard_avoid"])
    assert not bool(engine["mixed_category"])
    phrases = dictionary_phrase_rows(decisions, "engine_light_on")
    assert phrases["repair_item"].tolist() == ["check engine light", "engine light on"]


def test_evidence_status_distinguishes_verified_partial_and_provisional() -> None:
    assert pricing_evidence_status(_price()) == "Verified"
    assert pricing_evidence_status(_price(notes="Install only; excludes replacement carpet")) == "Partial"
    assert pricing_evidence_status(_price(confidence="low")) == "Provisional"
    assert pricing_evidence_status(_price(pricing_method="internal_default")) == "Provisional"
    assert pricing_evidence_status(_price(evidence_source="")) == "Missing"


def test_coverage_ledger_uses_exact_then_generic_without_calling_it_exact() -> None:
    matrix = pd.DataFrame(
        [
            {
                "canonical_defect": "paint_damage",
                "vehicle_class": "small_hatch",
                "cost_model": "cosmetic_panel",
                "status": "priced",
                "occurrences": 12,
            },
            {
                "canonical_defect": "paint_damage",
                "vehicle_class": "medium_suv",
                "cost_model": "cosmetic_panel",
                "status": "MISSING",
                "occurrences": 40,
            },
            {
                "canonical_defect": "window_damage",
                "vehicle_class": "van",
                "cost_model": "glass",
                "status": "generic",
                "occurrences": 5,
            },
        ]
    )
    schedule = pd.DataFrame(
        [
            _price(),
            _price(
                canonical_defect="window_damage",
                vehicle_class="generic",
                default_estimate=400,
                low_estimate=350,
                high_estimate=450,
            ),
        ]
    )

    ledger = pricing_coverage_ledger(matrix, schedule)

    exact = ledger[(ledger["canonical_defect"] == "paint_damage") & (ledger["vehicle_class"] == "small_hatch")].iloc[0]
    missing = ledger[(ledger["canonical_defect"] == "paint_damage") & (ledger["vehicle_class"] == "medium_suv")].iloc[0]
    generic = ledger[(ledger["canonical_defect"] == "window_damage") & (ledger["vehicle_class"] == "van")].iloc[0]
    assert exact["status"] == "Verified"
    assert missing["status"] == "Missing"
    assert generic["status"] == "Generic fallback"
    assert generic["evidence_quality"] == "Verified"
    assert generic["default_estimate"] == 400


def test_reviewed_pricing_candidates_ignore_a_superseded_add_rule() -> None:
    decisions = pd.DataFrame(
        [
            _decision(
                repair_key="clear coat peeling",
                canonical_defect="paint_clear_coat_peeling",
                cost_model="cosmetic_panel",
            ),
            _decision(
                repair_key="clear coat peeling",
                decision="Leave unclassified",
                canonical_defect="",
                cost_model="",
            ),
        ]
    )

    candidates = reviewed_pricing_candidates(decisions)

    assert "paint_clear_coat_peeling" not in set(candidates["canonical_defect"])


def test_matrix_builder_uses_latest_decision_per_repair_key(tmp_path) -> None:
    path = tmp_path / "decisions.csv"
    pd.DataFrame(
        [
            _decision(canonical_defect="obsolete_paint", cost_model="cosmetic_panel"),
            _decision(canonical_defect="paint_damage", cost_model="cosmetic_panel"),
        ]
    ).to_csv(path, index=False)

    canonicals = canonicals_needing_price(path)

    assert canonicals == {"paint_damage": "cosmetic_panel"}
