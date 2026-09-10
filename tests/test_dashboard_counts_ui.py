import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
import shared.navigation as navigation
import shared.data_loader as loader
import shared.global_filters as filters
import shared.valuation_display as display
import ops.active_monitor as monitor
from shared.dashboard_display import ai_scope_valuation_counts


def test_unique_eligible_coverage_excludes_history_and_blank_urls():
    scope = pd.DataFrame({"url": ["a", "a", "b", "", None]})
    saved = pd.DataFrame({"url": ["a", "a", "old", ""]})
    assert ai_scope_valuation_counts(scope, saved) == (1, 2)
    assert ai_scope_valuation_counts(pd.DataFrame(), saved) == (0, 0)


@pytest.mark.parametrize("eligible", [True, False])
def test_dashboard_labels_populations_and_empty_eligibility(monkeypatch, tmp_path, eligible):
    monkeypatch.setattr(navigation, "render_sidebar_navigation", lambda: None)
    monkeypatch.setattr(filters, "render_global_sidebar_filters", lambda: None)
    monkeypatch.setattr(loader, "ensure_datasets_available", lambda *a: [])
    monkeypatch.setattr(loader, "dataset_path", lambda name: tmp_path / name)
    active = pd.DataFrame([dict(url="a", make="Ford", model="Test", canonical_tag="tag", price=100,
                               bids=1, location="VIC", body_type="sedan", time_remaining_or_date_sold="1d")])
    for name in ["vehicle_static_details.csv", "active_vehicle_details.csv", "normalised_data.csv"]:
        active.to_csv(tmp_path / name, index=False)
    pd.DataFrame([dict(url="a", analysis_timestamp="2026-09-10T01:00:00Z", profit_margin_percent="10%",
                       score_out_of_10=8, confidence=.8),
                  dict(url="old", analysis_timestamp="2026-09-10T01:00:00Z", profit_margin_percent="10%",
                       score_out_of_10=8, confidence=.8)]).to_csv(tmp_path / "ai_listing_valuations.csv",index=False)
    monkeypatch.setattr(monitor, "load_ai_analysis_active_df", lambda: active if eligible else pd.DataFrame())
    monkeypatch.setattr(display, "build_ai_analysis_summary_rows", lambda *a, **k: pd.DataFrame())
    app = AppTest.from_file("DASHBOARD.py", default_timeout=30).run()
    assert not app.exception
    html = "\n".join(m.value for m in app.markdown)
    assert "100% of filtered active listings" not in html
    assert "File updated" in html and "UTC" in html
    assert next(m.value for m in app.metric if m.label == "Auction Houses") == "N/A"
    if eligible:
        assert "1 of 1 unique AI-eligible URLs before Buying View Filters" in html
        assert any("Check Buying View Filters" in i.value for i in app.info)
    else:
        assert "No AI-eligible URLs loaded; historical valuations are excluded" in html
        assert any("empty eligible set can be valid" in i.value for i in app.info)
