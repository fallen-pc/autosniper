from __future__ import annotations

import pandas as pd

from shared.repair_monitor import build_printable_repair_html, build_repair_monitor_rows, repair_monitor_summary


def test_repair_monitor_separates_actionable_outcomes() -> None:
    queue = pd.DataFrame(
        [
            {"repair_key": "tailgate cannot open", "repair_item": "tailgate needs attention cannot open.", "occurrences": 4, "listing_count": 2},
            {"repair_key": "coolant issue", "repair_item": "coolant issue.", "occurrences": 2, "listing_count": 2},
            {"repair_key": "unknown widget", "repair_item": "unknown widget concern.", "occurrences": 1, "listing_count": 1},
            {"repair_key": "bluetooth", "repair_item": "bluetooth.", "occurrences": 3, "listing_count": 3},
        ]
    )
    suggestions = pd.DataFrame(
        [
            {
                "repair_key": "unknown widget",
                "repair_item": "unknown widget concern.",
                "ai_decision": "Leave unclassified",
                "ai_canonical_defect": "",
                "ai_confidence": "0.8",
            }
        ]
    )

    rows = build_repair_monitor_rows(queue, suggestions)
    outcomes = dict(zip(rows["repair_key"], rows["outcome"]))

    assert outcomes == {
        "unknown widget": "Needs decision",
        "coolant issue": "Hard avoid",
        "tailgate cannot open": "Priced",
        "bluetooth": "Ignored / no cost",
    }
    priced = rows[rows["repair_key"] == "tailgate cannot open"].iloc[0]
    assert priced["canonical_defects"] == "tailgate_latch_or_tailgate_repair"
    assert repair_monitor_summary(rows) == {
        "total": 4,
        "priced": 1,
        "unpriced": 1,
        "hard_avoid": 1,
        "ignored": 1,
        "ai_pending": 3,
    }


def test_printable_repair_report_contains_all_outcomes() -> None:
    queue = pd.DataFrame(
        [
            {"repair_key": "tailgate cannot open", "repair_item": "tailgate needs attention cannot open.", "occurrences": 4, "listing_count": 2},
            {"repair_key": "unknown widget", "repair_item": "unknown widget concern.", "occurrences": 1, "listing_count": 1},
        ]
    )
    html = build_printable_repair_html(build_repair_monitor_rows(queue), generated_at="2026-09-13 00:00 UTC")

    assert "AutoSniper Current Repair Register" in html
    assert "tailgate needs attention cannot open" in html
    assert "unknown widget concern" in html
    assert "Needs decision" in html
    assert "Priced" in html
    assert "2026-09-13 00:00 UTC" in html


def test_production_monitor_page_is_read_only() -> None:
    source = open("pages/20_REPAIR_MONITOR.py", encoding="utf-8").read()

    assert "Save decision" not in source
    assert "upsert_decision" not in source
    assert "st.download_button" in source
