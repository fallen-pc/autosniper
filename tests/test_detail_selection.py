from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import shared.navigation as navigation
import shared.ops_utils as ops


VW = "https://www.grays.com/lot/0001/volkswagen-tiguan"
FIAT = "https://www.grays.com/lot/0002/fiat-freemont"


@pytest.fixture
def detail(monkeypatch):
    rows = pd.DataFrame([
        dict(url=VW, year=2014, make="Volkswagen", model="Tiguan", canonical_tag="vw"),
        dict(url=FIAT, year=2015, make="Fiat", model="Freemont", canonical_tag="fiat"),
    ])
    writes = []
    monkeypatch.setattr(navigation, "render_sidebar_navigation", lambda: None)
    for name in ("load_static_df", "load_active_df", "load_valuations_df"):
        monkeypatch.setattr(ops, name, lambda: rows.copy())
    for name in ("load_notes_df", "load_flags_df", "load_curves_df"):
        monkeypatch.setattr(ops, name, lambda: pd.DataFrame())
    monkeypatch.setattr(ops, "build_issue_index", lambda *a, **kw: rows.copy())
    monkeypatch.setattr(ops, "build_curve_meta", lambda df: {
        tag: SimpleNamespace(anchor_years=[2014, 2015], last_updated="2026-09-10")
        for tag in ("vw", "fiat")
    })
    for name in ("append_note", "append_flag", "append_curve_queue"):
        monkeypatch.setattr(ops, name, lambda *args, _name=name: writes.append((_name, *args)))
    app = AppTest.from_file(str(Path("pages/02_DETAIL.py")), default_timeout=20)
    app.session_state["ops_selected_url"] = VW
    app.run()
    assert not app.exception
    return app, writes


def assert_vehicle(app, url, name):
    assert not app.exception
    assert app.selectbox(key="detail_url_choice").value == url
    assert app.text_input(key="detail_url_input").value == url
    assert app.session_state["ops_selected_url"] == url
    assert any(name in item.value for item in app.markdown)
    assert app.get("link_button")[0].proto.url == url
    for table in app.dataframe[:3]:
        assert table.value["url"].tolist() == [url]


def test_dropdown_after_exceptions_handoff_updates_record_and_write_targets(detail):
    app, writes = detail
    assert_vehicle(app, VW, "Volkswagen Tiguan")
    app.selectbox(key="detail_url_choice").select(FIAT).run()
    assert_vehicle(app, FIAT, "Fiat Freemont")
    app.text_area(key="detail_note_text").input("Fiat inspection note").run()
    app.button(key="detail_save_note").click().run()
    app.selectbox(key="detail_flag_choice").select("WITHDRAWN").run()
    app.text_input(key="detail_flag_reason").input("Fiat withdrawn").run()
    app.button(key="detail_save_flag").click().run()
    app.button(key="detail_curve_queue").click().run()
    assert writes == [
        ("append_note", FIAT, "Fiat inspection note"),
        ("append_flag", FIAT, "WITHDRAWN", "Fiat withdrawn"),
        ("append_curve_queue", FIAT, "fiat"),
    ]


def test_pasted_url_then_dropdown_and_blank_input_stay_synchronized(detail):
    app, _ = detail
    app.text_input(key="detail_url_input").input("  " + FIAT + "  ").run()
    assert_vehicle(app, FIAT, "Fiat Freemont")
    app.text_input(key="detail_url_input").input("").run()
    assert_vehicle(app, FIAT, "Fiat Freemont")
    app.selectbox(key="detail_url_choice").select(VW).run()
    assert_vehicle(app, VW, "Volkswagen Tiguan")


@pytest.mark.parametrize("via_handoff", [False, True])
def test_vehicle_change_clears_drafts_but_normal_rerun_preserves_them(detail, via_handoff):
    app, writes = detail
    app.text_area(key="detail_note_text").input("Volkswagen only").run()
    app.selectbox(key="detail_flag_choice").select("BROKEN_URL").run()
    app.text_input(key="detail_flag_reason").input("Volkswagen reason").run()
    app.run()
    assert app.text_area(key="detail_note_text").value == "Volkswagen only"
    if via_handoff:
        app.session_state["ops_selected_url"] = FIAT
        app.run()
    else:
        app.selectbox(key="detail_url_choice").select(FIAT).run()
    assert_vehicle(app, FIAT, "Fiat Freemont")
    assert app.text_area(key="detail_note_text").value == ""
    assert app.selectbox(key="detail_flag_choice").value == ""
    assert app.text_input(key="detail_flag_reason").value == ""
    app.button(key="detail_save_note").click().run()
    app.button(key="detail_save_flag").click().run()
    assert writes == []


def test_unknown_pasted_url_does_not_leave_previous_vehicle_actions_available(detail):
    app, writes = detail
    unknown = "https://www.grays.com/lot/unknown"
    app.text_input(key="detail_url_input").input(unknown).run()
    assert not app.exception
    assert app.selectbox(key="detail_url_choice").value == unknown
    assert any("URL not found" in warning.value for warning in app.warning)
    assert not app.button
    assert writes == []
    app.selectbox(key="detail_url_choice").select(VW).run()
    assert_vehicle(app, VW, "Volkswagen Tiguan")
