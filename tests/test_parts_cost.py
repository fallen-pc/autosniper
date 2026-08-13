from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared import parts_cost


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("P.O.A", None),
        ("poa", None),
        ("N/A", None),
        ("no price here", None),
        ("$125", 125.0),
        ("$1,250.50", 1250.5),
        (330, 330.0),
    ],
)
def test_parse_price_value_scalar_inputs(raw, expected) -> None:
    assert parts_cost._parse_price_value(raw) == expected


def test_parse_price_value_averages_multiple_numbers() -> None:
    assert parts_cost._parse_price_value("$100/$200") == 150.0
    assert parts_cost._parse_price_value("$100 \\ $300") == 200.0


@pytest.mark.parametrize(
    ("severity", "tier"),
    [(0, "low"), (10, "low"), (11, "mid"), (30, "mid"), (31, "high"), (500, "high")],
)
def test_severity_tier_boundaries(severity, tier) -> None:
    assert parts_cost._severity_tier(severity) == tier


def test_load_price_table_drops_section_headers_and_derives_base_price(tmp_path) -> None:
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "part,pick_price,warranty_price,core_deposit,models_2008_on\n"
        "A,A,A,A,A\n"
        "Front Bumper,$100,$200,,P.O.A\n",
        encoding="utf-8",
    )

    table = parts_cost._load_price_table(csv_path)

    assert list(table["part"]) == ["Front Bumper"]
    assert list(table["part_lower"]) == ["front bumper"]
    assert table["base_price"].iloc[0] == 150.0


def test_load_price_table_reads_bundled_lookup() -> None:
    table = parts_cost._load_price_table(ROOT / parts_cost.PRICE_LOOKUP_PATH)

    assert not table.empty
    assert {"part_lower", "base_price"}.issubset(table.columns)
    assert table["base_price"].notna().any()


def test_tag_base_costs_uses_keyword_median_and_defaults(monkeypatch) -> None:
    import pandas as pd

    table = pd.DataFrame(
        {
            "part_lower": ["front bumper", "rear bumper", "alloy wheel"],
            "base_price": [100.0, 300.0, 250.0],
        }
    )
    monkeypatch.setattr(parts_cost, "_load_price_table", lambda: table)
    parts_cost._tag_base_costs.cache_clear()

    try:
        costs = parts_cost._tag_base_costs()
    finally:
        parts_cost._tag_base_costs.cache_clear()

    assert costs["body_exterior"] == 200.0
    assert costs["tyres_wheels"] == 250.0
    # No matching parts -> falls back to the hard-coded default.
    assert costs["engine_mechanical"] == parts_cost.DEFAULT_BASE_COSTS["engine_mechanical"]
    # Tag without keywords always uses the default.
    assert costs["unknown_untested"] == parts_cost.DEFAULT_BASE_COSTS["unknown_untested"]


def test_estimate_parts_cost_applies_tier_multiplier_and_serializes_details(monkeypatch) -> None:
    monkeypatch.setattr(parts_cost, "_tag_base_costs", lambda: {"body_exterior": 200.0, "interior": 100.0})

    total, details_json = parts_cost.estimate_parts_cost(["body_exterior", "interior"], severity=40)

    assert total == 450.0
    details = json.loads(details_json)
    assert [item["tag"] for item in details] == ["body_exterior", "interior"]
    assert all(item["tier"] == "high" and item["multiplier"] == 1.5 for item in details)
    assert [item["base_cost"] for item in details] == [200.0, 100.0]


def test_estimate_parts_cost_skips_blank_tags_and_defaults_unknown_tags(monkeypatch) -> None:
    monkeypatch.setattr(parts_cost, "_tag_base_costs", lambda: {})

    total, details_json = parts_cost.estimate_parts_cost([" ", "", "electrical", "not_a_tag"], severity=5)

    details = json.loads(details_json)
    assert [item["tag"] for item in details] == ["electrical", "not_a_tag"]
    assert total == round(parts_cost.DEFAULT_BASE_COSTS["electrical"] * 0.6, 2)


def test_estimate_parts_cost_with_no_tags_returns_zero(monkeypatch) -> None:
    monkeypatch.setattr(parts_cost, "_tag_base_costs", lambda: {})

    assert parts_cost.estimate_parts_cost([], severity=15) == (0.0, "[]")
