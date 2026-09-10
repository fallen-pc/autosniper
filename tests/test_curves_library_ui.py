import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
import shared.curves as curves
import shared.ops_utils as ops
import shared.navigation as navigation
import shared.runtime as runtime
import shared.csv_utils as csv_utils


@pytest.fixture
def curve_page(monkeypatch):
    grid = pd.DataFrame([
        dict(canonical_tag="base", anchor_year=2015, km_bucket=100000,
             price_low=4000, price_mid=5000, price_high=6000),
        dict(canonical_tag="base", anchor_year=2016, km_bucket=100000,
             price_low=4500, price_mid=5500, price_high=6500),
    ])
    monkeypatch.setattr(navigation, "render_sidebar_navigation", lambda: None)
    monkeypatch.setattr(ops, "load_curves_df", lambda: grid.copy())
    monkeypatch.setattr(ops, "load_active_df", lambda: pd.DataFrame([
        dict(url="one", canonical_tag="alias"), dict(url="two", canonical_tag="alias")]))
    monkeypatch.setattr(ops, "load_static_df", lambda: pd.DataFrame([
        dict(canonical_tag="alias"), dict(canonical_tag="missing")]))
    monkeypatch.setattr(csv_utils, "read_csv_or_empty", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(curves, "load_curve_aliases", lambda: {"alias": "base"})
    monkeypatch.setattr(ops, "load_curve_aliases", lambda: {"alias": "base"})
    monkeypatch.setattr(curves, "load_curve_groups_v2", lambda: pd.DataFrame())
    monkeypatch.setattr(ops, "load_curve_groups_v2", lambda: pd.DataFrame())
    monkeypatch.setattr(runtime, "is_vps_runtime", lambda: True)
    return lambda: AppTest.from_file("pages/03_CURVES.py", default_timeout=20).run()


def test_production_inspects_alias_grid_without_dead_editor(curve_page):
    app = curve_page()
    assert not app.exception
    assert [m.value for m in app.metric[:3]] == ["3", "2", "1"]
    library = app.dataframe[1].value.set_index("canonical_tag")
    assert library.loc["alias", "active_count"] == 2
    assert library.loc["base", "active_count"] == 0
    assert library.loc["alias", "curve_rows"] == 2
    assert library.loc["alias", "curve_source"] == "base"
    assert app.dataframe[-1].value["price_mid"].tolist() == [5000, 5500]
    assert not app.button
    assert any("development workspace" in item.value for item in app.info)
    assert any("Not recorded" in item.value for item in app.caption)
    app.selectbox[0].select("missing").run()
    assert not app.exception
    assert any("No saved curve for this tag" in item.value for item in app.warning)
    assert app.metric[-1].value == "0"


def test_search_is_literal_and_recovers_after_no_matches(curve_page):
    app = curve_page()
    app.text_input[0].set_value("[").run()
    assert not app.exception
    assert any("No tags match" in item.value for item in app.info)
    app.text_input[0].set_value("base").run()
    assert not app.exception
    assert app.selectbox[0].value == "base"
    assert app.metric[-2].value == "0"


def test_development_keeps_builder_button(curve_page, monkeypatch):
    monkeypatch.setattr(runtime, "is_vps_runtime", lambda: False)
    app = curve_page()
    assert not app.exception
    assert app.button[0].label == "Open Curve Builder V2"


def test_empty_library_is_usable(curve_page, monkeypatch):
    for name in ("load_curves_df", "load_active_df", "load_static_df"):
        monkeypatch.setattr(ops, name, lambda: pd.DataFrame())
    app = curve_page()
    assert not app.exception
    assert [m.value for m in app.metric] == ["0", "0", "0"]
    assert any("No tags match" in item.value for item in app.info)


def test_missing_curve_file_keeps_observed_tags_reviewable(curve_page, monkeypatch):
    monkeypatch.setattr(ops, "load_curves_df", lambda: pd.DataFrame())
    app = curve_page()
    assert not app.exception
    assert app.metric[2].value == "2"
    assert app.metric[-1].value == "0"
    assert any("No saved curve for this tag" in item.value for item in app.warning)
