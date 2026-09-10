from types import SimpleNamespace
import subprocess
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
import shared.navigation as navigation
import shared.data_loader as loader
import shared.curves as curves


@pytest.fixture
def pipeline_page(monkeypatch, tmp_path):
    monkeypatch.setattr(navigation, "render_sidebar_navigation", lambda: None)
    monkeypatch.setattr(loader, "dataset_path", lambda name: tmp_path / name)
    monkeypatch.setattr(curves, "load_curves", lambda: pd.DataFrame())
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="Missing input; nothing changed.", stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    pd.DataFrame([dict(url="one")]).to_csv(tmp_path / "normalised_data.csv", index=False)
    pd.DataFrame([dict(url="one"), dict(url="two")]).to_csv(tmp_path / "vehicle_static_details.csv", index=False)
    return calls, tmp_path


@pytest.mark.parametrize("stage,key,tail", [
    ("Links", "panel_stage1_run", ["scripts/extract_links.py"]),
    ("Details", "panel_stage2_run", ["scripts/extract_vehicle_details.py", "--raw-only"]),
    ("Normalise", "panel_stage3_run", ["scripts/pipeline_stages.py", "normalize"]),
    ("Exclude", "panel_stage4_run", ["scripts/pipeline_stages.py", "exclude"]),
    ("Canonical", "panel_stage5_run", ["scripts/pipeline_stages.py", "match"]),
    ("Active", "panel_stage6_bids_run", ["scripts/update_bids.py", "--limit", "25", "--batch-interval", "5", "--skip-master"]),
    ("Active", "panel_stage6_master_run", ["scripts/update_master.py"]),
    ("Audit", "panel_stage7_run", ["scripts/pipeline_stages.py", "audit"]),
])
def test_inspection_never_runs_command_and_explicit_action_keeps_scope(pipeline_page, stage, key, tail):
    calls, _ = pipeline_page
    app = AppTest.from_file("pages/12_GRAYS_PIPELINE.py", default_timeout=20)
    app.session_state["pipeline_stage_selector"] = stage
    app.run()
    assert not app.exception
    assert not calls
    app.button(key=key).click().run()
    assert not app.exception
    assert len(calls) == 1 and calls[0][1:] == tail
    assert not app.success
    assert any("whether any records changed" in m.value for m in app.info)
    assert app.code[0].value == "Missing input; nothing changed."


def test_exclusions_shows_saved_totals_without_inventing_run_counts(pipeline_page):
    app = AppTest.from_file("pages/12_GRAYS_PIPELINE.py", default_timeout=20)
    app.session_state["pipeline_stage_selector"] = "Exclude"
    app.run()
    assert not app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Saved normalised rows"] == "1"
    assert metrics["Saved static rows"] == "2"
    assert "Written to static" not in metrics
    assert any("log is cumulative" in c.value for c in app.caption)


def test_schema_inspection_includes_state_and_does_not_write(pipeline_page):
    calls, root = pipeline_page
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    app = AppTest.from_file("pages/12_GRAYS_PIPELINE.py", default_timeout=20)
    app.session_state["pipeline_stage_selector"] = "Audit"
    app.run()
    assert not app.exception
    assert not calls
    assert "vehicle_state.csv" in app.dataframe[0].value["dataset"].tolist()
    assert any("extra columns are removed" in c.value for c in app.caption)
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}


def test_clear_stage_selection_has_safe_default(pipeline_page):
    app = AppTest.from_file("pages/12_GRAYS_PIPELINE.py", default_timeout=20)
    app.session_state["pipeline_stage_selector"] = None
    app.run()
    assert not app.exception
    assert app.button(key="panel_stage1_run")
