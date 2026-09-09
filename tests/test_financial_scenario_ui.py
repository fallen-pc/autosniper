from __future__ import annotations

import ast
import html
from pathlib import Path
from typing import Optional

import pandas as pd
import pytest

from shared.valuation_display import (
    build_ai_analysis_summary_rows, valuation_scenario_values,
    valuation_next_step, valuation_snapshot_caption, parse_currency_value, first_currency_value,
)


def page_functions(*names, **context):
    path = Path(__file__).parents[1] / "pages" / "6_AI_ANALYSIS.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = dict(pd=pd, html=html, Optional=Optional,
                     valuation_scenario_values=valuation_scenario_values,
                     parse_currency=parse_currency_value, first_currency_value=first_currency_value, **context)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("downside", [1543, 0, -200, None, float("nan")])
def test_dashboard_and_analysis_share_same_saved_scenario(downside):
    row = dict(url="captiva", action_label="Buy", computed_verdict="Conditional Flip",
               bid_status="Cheap", hard_max_safety="Strong", profit_at_current_bid_worst=3000,
               recommended_max_bid=1762, net_profit_worst=1171, resale_mid=5620,
               confidence=.8, expected_auction_bid_basis_value=1540,
               expected_auction_price=2460, expected_auction_profit=2553,
               expected_auction_worst_profit_value=downside)
    summary = build_ai_analysis_summary_rows(pd.DataFrame([dict(url="captiva", price=518)]),
                                             pd.DataFrame([row]), min_profit=1000)
    expected = valuation_scenario_values(row)["finish_downside"]
    actual = summary.iloc[0]["expected_finish_profit_value"]
    assert (pd.isna(actual) and expected is None) or actual == expected
    assert summary.iloc[0]["expected_finish_value"] == 1540


def test_missing_downside_never_substitutes_midpoint_or_current_profit():
    values = valuation_scenario_values(dict(net_profit_mid=5000, expected_auction_profit=2553,
                                           profit_at_current_bid_worst=9000))
    assert values["finish_downside"] is None
    assert values["net_downside"] is None
    assert valuation_scenario_values(dict(no_edge_at_current_bid=True))["net_label"] == "Downside profit at current bid"


def test_saved_repairs_and_zero_finish_do_not_recalculate_or_fall_back():
    funcs = page_functions("_repair_deduction_value", "_format_repair_max_bid_deduction",
                           "_expected_finish_display_parts", _format_currency_value=lambda x: x,
                           _format_price_text=lambda x: x, _expected_finish_cap_status=lambda row: "",
                           _safe_text=lambda x, fallback="": x or fallback, _truthy=lambda x: False)
    row = pd.Series(dict(repair_estimate=253, repair_estimate_high_value=394,
                         expected_auction_bid_basis=0, expected_auction_price=2460))
    assert funcs["_repair_deduction_value"](row) == 253
    assert funcs["_format_repair_max_bid_deduction"](row) == 394
    assert funcs["_expected_finish_display_parts"](row)[0] == 0
    assert funcs["_repair_deduction_value"](pd.Series(dtype=object)) is None


def test_cost_total_does_not_treat_unknown_cost_as_free():
    fn = page_functions("_compute_auction_cost_value")["_compute_auction_cost_value"]
    row = pd.Series(dict(fees_estimate=200, transport_estimate=100, rego_estimate=0,
                         roadworthy_estimate=100, prep_estimate=0, repair_estimate=253))
    assert fn(row) == 653
    assert fn(row.drop("transport_estimate")) is None


def test_review_identifies_missing_context_and_does_not_instruct_bidding():
    assert "valuation verdict" in valuation_next_step({})
    text = valuation_next_step(dict(action_label="Review", computed_verdict="Review (unresolved repairs)",
                                    bid_status="Cheap", hard_max_safety="Strong"))
    assert "unresolved repairs" in text
    assert "proxy max" not in text
    assert "do not bid" in valuation_next_step(dict(action_label="Avoid", bid_policy_gate="INTERSTATE"))
    assert "inspect condition" in valuation_next_step(dict(action_label="Buy"))


def test_snapshot_time_and_high_risk_badge():
    assert "time unavailable" in valuation_snapshot_caption({})
    assert "09 Sep 2026 15:15:28 UTC" in valuation_snapshot_caption(dict(analysis_timestamp="2026-09-09T15:15:28+00:00"))
    funcs = page_functions("_confidence_badges_html", "_badge_tone",
                           _safe_text=lambda x, fallback="": x or fallback)
    markup = funcs["_confidence_badges_html"]("High", "High", "High")
    assert 'confidence-badge badge-low' in markup.split("Data Completeness")[1]
    assert markup.count('confidence-badge badge-high') == 2


def test_currency_bullets_render_literal_dollars():
    from streamlit.testing.v1 import AppTest
    path = Path(__file__).parents[1] / "pages" / "6_AI_ANALYSIS.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    source = next(ast.get_source_segment(path.read_text(encoding="utf-8"), node)
                  for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_render_bullets")
    app = AppTest.from_string("import streamlit as st\n" + source +
                              "\n_render_bullets('Repairs', ['$253 likely; $394 conservative'])").run()
    assert not app.exception
    assert app.markdown[1].value == r"- \$253 likely; \$394 conservative"


def test_bid_logic_renders_saved_snapshot_without_recomputing():
    from streamlit.testing.v1 import AppTest
    path = Path(__file__).parents[1] / "pages" / "6_AI_ANALYSIS.py"
    source = path.read_text(encoding="utf-8")
    names = {"_render_bid_logic_tab", "_repair_deduction_value", "_format_repair_max_bid_deduction",
             "_compute_auction_cost_value", "_format_currency_value", "_format_currency",
             "_format_price_text", "_format_percent", "_safe_text", "_curve_confidence_label",
             "_expected_finish_display_parts", "_expected_finish_cap_status", "_truthy",
             "_compute_resale_value", "_display_profit_label", "_render_bullets"}
    functions = "\n\n".join(ast.get_source_segment(source, node) for node in ast.parse(source).body
                              if isinstance(node, ast.FunctionDef) and node.name in names)
    script = """import streamlit as st
import pandas as pd
from typing import Optional
from shared.valuation_display import *
parse_currency = parse_currency_value
""" + functions + """
row = pd.Series(dict(action_label='Buy', computed_verdict='Conditional Flip',
    recommended_max_bid=1762, net_profit_worst=1171, resale_mid=5620,
    confidence=.8, expected_auction_bid_basis=1540, expected_auction_profit=2553,
    expected_auction_worst_profit=1543, repair_estimate=253, repair_estimate_high=394,
    fees_estimate=200, transport_estimate=100, rego_estimate=0, roadworthy_estimate=100,
    prep_estimate=0, analysis_timestamp='2026-09-09T15:15:28+00:00'))
_render_bid_logic_tab(row, risk_items=[])
"""
    app = AppTest.from_string(script).run()
    assert not app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Downside profit at expected finish"] == "$1,543"
    assert metrics["Saved repair allowance"] == "$253"
    assert metrics["Saved conservative repair reserve"] == "$394"
    assert metrics["Costs excluding hammer"] == "$653"
    assert "15:15:28 UTC" in app.caption[0].value
