from __future__ import annotations

import pandas as pd

from scripts.build_repair_quote_batch import already_open, top_missing_cells


def _matrix(rows):
    return pd.DataFrame(rows)


def test_top_missing_cells_filters_to_missing_and_sorts_by_occurrences(tmp_path) -> None:
    path = tmp_path / "matrix.csv"
    _matrix(
        [
            {"canonical_defect": "a", "vehicle_class": "ute", "cost_model": "cosmetic_panel", "status": "MISSING", "occurrences": 50},
            {"canonical_defect": "b", "vehicle_class": "van", "cost_model": "cosmetic_panel", "status": "priced", "occurrences": 9999},
            {"canonical_defect": "c", "vehicle_class": "medium_suv", "cost_model": "cosmetic_panel", "status": "MISSING", "occurrences": 500},
        ]
    ).to_csv(path, index=False)

    out = top_missing_cells(path, top_n=10)

    assert list(out["canonical_defect"]) == ["c", "a"]
    assert "b" not in set(out["canonical_defect"])


def test_top_missing_cells_respects_top_n(tmp_path) -> None:
    path = tmp_path / "matrix.csv"
    _matrix(
        [
            {"canonical_defect": str(i), "vehicle_class": "ute", "cost_model": "cosmetic_panel",
             "status": "MISSING", "occurrences": i}
            for i in range(30)
        ]
    ).to_csv(path, index=False)

    out = top_missing_cells(path, top_n=5)

    assert len(out) == 5
    assert list(out["occurrences"]) == [29, 28, 27, 26, 25]


def test_already_open_true_for_a_live_status() -> None:
    quotes = pd.DataFrame(
        [{"canonical_defect": "seat_damage", "vehicle_class": "medium_suv", "status": "sent"}]
    )

    assert already_open(quotes, "seat_damage", "medium_suv") is True


def test_already_open_false_for_a_dead_end_status() -> None:
    # A prior request that was declined/superseded should not block redrafting.
    quotes = pd.DataFrame(
        [{"canonical_defect": "seat_damage", "vehicle_class": "medium_suv", "status": "no_quote"}]
    )

    assert already_open(quotes, "seat_damage", "medium_suv") is False


def test_already_open_false_for_a_different_class() -> None:
    quotes = pd.DataFrame(
        [{"canonical_defect": "seat_damage", "vehicle_class": "small_hatch", "status": "sent"}]
    )

    assert already_open(quotes, "seat_damage", "medium_suv") is False


def test_already_open_false_when_quotes_is_empty() -> None:
    assert already_open(pd.DataFrame(), "seat_damage", "medium_suv") is False
