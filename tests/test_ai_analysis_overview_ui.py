from pathlib import Path


def test_overview_renders_confidence_profile_and_analysis_diagnostics():
    source = (Path(__file__).parents[1] / "pages" / "6_AI_ANALYSIS.py").read_text(
        encoding="utf-8"
    )

    overview = source.split("with overview_tab:", maxsplit=1)[1].split(
        "with curve_tab:", maxsplit=1
    )[0]
    assert "_confidence_badges_html" in overview
    assert '_render_bullets("Listing profile"' in overview
    assert 'row.get("confidence_notes")' in overview
    assert 'row.get("expected_sale_note")' in overview
