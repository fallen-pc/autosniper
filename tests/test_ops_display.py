import ast
from pathlib import Path
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from shared.ops_display import reason_category, filtered_issue_summary, issue_guidance
import shared.ops_utils as ops
import shared.navigation as navigation


@pytest.mark.parametrize("reason,category", [
    ("[ok]", "Successful records"), ("[out_of_scope]", "Expected scope exclusions"),
    ("[disallowed_variant]", "Expected scope exclusions"),
    ("[MISSING_YEAR]", "Data needing review"), ("[ambig_fuel]", "Data needing review"),
    ("FETCH_FAILED", "Collection failures"), ("new_reason", "Unclassified — investigate"),
    (None, "Unclassified — investigate"), ("[ok][BAD_PARSE]", "Unclassified — investigate"),
])
def test_reason_categories_do_not_treat_unknown_or_success_as_failure(reason, category):
    assert reason_category(reason) == category


def test_buckets_count_unique_urls_in_filtered_population():
    df = pd.DataFrame([dict(url=url, issue_code=issue) for url, issue in
                       [("a", "NO_CURVE"), ("a", "NO_CURVE"), ("a", "BAD_PARSE"), ("b", "NO_CURVE")]])
    counts = filtered_issue_summary(df, ["a"]).set_index("issue_code")["count"].to_dict()
    assert counts == {"BAD_PARSE": 1, "NO_CURVE": 1}
    assert "not a scraper failure" in issue_guidance("NO_CURVE")[0]
    assert "No repair is needed" in issue_guidance("NOT_ACTIVE")[1]


def test_exceptions_bucket_and_rows_change_together(monkeypatch):
    static = pd.DataFrame([dict(url=u, make=m, model="Model", canonical_tag="tag")
                           for u,m in [("a","Ford"),("b","Toyota")]])
    active = pd.DataFrame([dict(url=u,status="active" if u == "a" else "sold",time_remaining_or_date_sold="2d",price=100,bids=1)
                           for u in ("a","b")])
    issues = pd.DataFrame([dict(url=u,issue_count=1,issue_codes=["NO_CURVE"],issue_summary="No curve")
                          for u in ("a","b")])
    monkeypatch.setattr(navigation, "render_sidebar_navigation", lambda: None)
    monkeypatch.setattr(ops,"load_static_df",lambda: static.copy())
    monkeypatch.setattr(ops,"load_active_df",lambda: active.copy())
    for name in ("load_valuations_df","load_flags_df","load_curves_df"):
        monkeypatch.setattr(ops,name,lambda: pd.DataFrame())
    monkeypatch.setattr(ops,"build_curve_meta",lambda df: {})
    monkeypatch.setattr(ops,"build_issue_index",lambda *a,**kw: issues.copy())
    app=AppTest.from_file("pages/01_EXCEPTIONS.py",default_timeout=20).run()
    assert not app.exception
    assert app.dataframe[0].value["count"].tolist()==[2]
    app.multiselect(key="ops_make_filter").set_value(["Ford"]).run()
    assert not app.exception
    assert app.dataframe[0].value["count"].tolist()==[1]
    assert app.dataframe[1].value["url"].tolist()==["a"]
    assert any("supported buying scope" in m.value for m in app.markdown)
    app.multiselect(key="ops_status_filter").set_value(["sold"]).run()
    assert not app.exception
    assert any("No issue records match" in item.value for item in app.info)


def test_health_renders_success_separately_from_data_review():
    source=Path("pages/05_HEALTH.py").read_text(encoding="utf-8")
    fn=next(ast.get_source_segment(source,n) for n in ast.parse(source).body
            if isinstance(n,ast.FunctionDef) and n.name=="_render_reason_groups")
    script="import pandas as pd\nimport streamlit as st\nfrom shared.ops_display import reason_category\n"+fn
    script+="\n_render_reason_groups(pd.DataFrame([dict(reason_code='[ok]',count=947),dict(reason_code='[BAD_PARSE]',count=82)]))"
    app=AppTest.from_string(script).run()
    assert not app.exception
    assert app.dataframe[0].value["reason_code"].tolist()==["[BAD_PARSE]"]
    assert app.dataframe[1].value["reason_code"].tolist()==["[ok]"]
