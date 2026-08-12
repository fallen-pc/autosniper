from pathlib import Path


PAGE_PATH = Path(__file__).parents[1] / "pages" / "6_AI_ANALYSIS.py"


def test_ai_analysis_reuses_monitor_external_lifecycle_and_eligibility() -> None:
    source = PAGE_PATH.read_text(encoding="utf-8")

    assert "_load_external_auction_active_rows" in source
    assert "_exclude_shortlist_ineligible_rows" in source
    assert "external_active_df = load_external_active_data()" in source
    assert "pd.concat([active_df, external_active_df]" in source


def test_external_rows_are_added_after_grays_tag_merge_and_before_curve_checks() -> None:
    source = PAGE_PATH.read_text(encoding="utf-8")

    tag_merge = source.index("active_df = active_df.merge(active_groups")
    external_merge = source.index("external_active_df = load_external_active_data()")
    numeric_refresh = source.index(
        'active_df["odometer_numeric"] = active_df["odometer_reading"].apply(parse_numeric)',
        external_merge,
    )
    curve_check = source.index('active_df["curve_coverage"] = (')

    assert tag_merge < external_merge < numeric_refresh < curve_check
