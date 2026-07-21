from pathlib import Path

from shared.navigation import HIDDEN_ROUTABLE_PAGES, navigation_spec
from shared.scraper_health import friendly_health_failure


RETIRED_PAGE_PATHS = {
    "pages/1_LINK_EXTRACTOR.py",
    "pages/2_VEHICLE_DETAIL_EXTRACTOR.py",
    "pages/4_MASTER_DATABASE.py",
    "pages/04_MAPPINGS.py",
    "pages/8_REAUCTION_MONITOR.py",
    "pages/10_BIDDER_INSIGHTS.py",
    "pages/11_TOYOTA_COVERAGE.py",
    "pages/99_STYLE_GUIDE.py",
    "pages/8_MODEL_ACCURACY.py",
    "pages/16_VALUATION_CALIBRATION.py",
}


def test_navigation_exposes_only_current_workflow_surfaces() -> None:
    spec = navigation_spec()
    pages = [entry for entries in spec.values() for entry in entries]
    paths = {path for path, _title, _default in pages}
    titles = {title for _path, title, _default in pages}

    assert "pages/6_AI_ANALYSIS.py" in paths
    assert "pages/17_MODEL_PROOF.py" in paths
    assert paths.isdisjoint(RETIRED_PAGE_PATHS)
    assert all(not Path(path).exists() for path in RETIRED_PAGE_PATHS)
    assert "Active Inventory" in titles
    assert "COVERAGE" not in spec
    assert any(title == "Autotrader Scraper" for _path, title, _default in spec["OPERATIONS"])
    assert HIDDEN_ROUTABLE_PAGES == []


def test_health_failure_summary_does_not_expose_raw_exception() -> None:
    raw_error = "Playwright TimeoutError: page.goto manheim navigation timeout at internal/file.py:88"

    summary = friendly_health_failure("manheim_scrape", raw_error)

    assert summary.startswith("The latest Manheim scrape did not complete.")
    assert "Playwright" not in summary
    assert "internal/file.py" not in summary
