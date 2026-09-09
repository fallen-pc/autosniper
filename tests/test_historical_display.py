from pathlib import Path
import ast
import pandas as pd
import pytest
from shared.valuation_display import bid_display_parts

PAGE = Path(__file__).parents[1] / "pages" / "8_MISSED_OPPORTUNITIES.py"


def test_review_bid_cap_is_reference_not_instruction():
    for action in ("Review", "Watch", "Avoid"):
        parts = bid_display_parts(dict(action_label=action, recommended_max_bid=1339, price=409))
        assert "Enter as" not in parts["max_detail"]
        assert "Reference ceiling" in parts["max_detail"]


@pytest.mark.parametrize("action", ["Buy", "Watch", "Review", "Avoid"])
def test_sold_actions_are_retrospective(action):
    tree = ast.parse(PAGE.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"sold_action_parts", "safe_text", "_to_float"}]
    namespace = dict(pd=pd)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(PAGE), "exec"), namespace)
    label, detail, _ = namespace["sold_action_parts"](pd.Series(dict(action_label=action)))
    assert label.startswith("Historical")
    assert "auction has ended" in detail
    assert "auction-site" not in detail


def test_miss_summary_obeys_profit_filter():
    source = PAGE.read_text(encoding="utf-8")
    block = source[source.index("view = eligible_view.copy()"):source.index("if sold_count == 0:")]
    rows = pd.DataFrame([dict(missed=True, projected_profit_at_sold=100, delta=300,
                             profit_margin_pct=5, underbid_pct=2),
                         dict(missed=True, projected_profit_at_sold=1000, delta=1200,
                              profit_margin_pct=20, underbid_pct=10)])
    ns = dict(pd=pd, eligible_view=rows, no_curve_view=pd.DataFrame(), only_missed=True,
              min_metric=500, only_net_positive=True)
    exec(block, ns)
    assert ns["sold_count"] == 1
    assert ns["with_curve"] == 2
    assert ns["avg_missed_margin"] == 20
    assert ns["avg_underbid_pct"] == 10
    assert ns["true_miss_view"]["projected_profit_at_sold"].tolist() == [1000]


@pytest.mark.parametrize("choice,expected", [
    ("Profit at sold price (high to low)", ["a", "b", "c"]),
    ("Sold price (low to high)", ["c", "a", "b"]),
    ("Odometer (low to high)", ["b", "c", "a"]),
])
def test_rendered_cards_keep_global_selected_order(choice, expected):
    source = PAGE.read_text(encoding="utf-8")
    block = source[source.index("sort_df = view.copy()"):]
    rows = pd.DataFrame([
        dict(url="a", make="Toyota", model="X", projected_profit_at_sold=300, sold_price=200, odometer_numeric=30),
        dict(url="b", make="Ford", model="Y", projected_profit_at_sold=200, sold_price=300, odometer_numeric=10),
        dict(url="c", make="Toyota", model="X", projected_profit_at_sold=100, sold_price=100, odometer_numeric=20),
    ])
    captured = []
    class UI:
        def selectbox(self, *args, **kwargs): return 20
        def caption(self, *args): pass
        def markdown(self, *args, **kwargs): pass
    ns = dict(pd=pd, st=UI(), view=rows, sort_choice=choice, only_missed=True, include_repairs=True,
              render_sold_analysis_card=lambda row, **kwargs: captured.append(row["url"]))
    exec(block, ns)
    assert captured == expected
