from __future__ import annotations

import pandas as pd

import shared.curves as curves
from scripts.generate_curve_candidates import build_curve_candidates


def _make_rows(canonical_tag: str, years: list[int], prices: list[int], odometers: list[int]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for year, price, odometer in zip(years, prices, odometers):
        rows.append(
            {
                "canonical_tag": canonical_tag,
                "year": year,
                "price": price,
                "odometer_reading": odometer,
            }
        )
    return rows


def test_build_curve_candidates_groups_alias_tags(monkeypatch, tmp_path):
    alias_path = tmp_path / "curve_aliases.csv"
    alias_path.write_text(
        "canonical_tag,base_curve\n"
        "mazda_3_maxx_petrol_auto_hatch_bl,mazda_3_neo_petrol_auto_hatch_bl\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(curves, "CURVE_ALIASES_PATH", alias_path)
    curves.load_curve_aliases.cache_clear()

    base_tag = "mazda_3_neo_petrol_auto_hatch_bl"
    alias_tag = "mazda_3_maxx_petrol_auto_hatch_bl"
    tagged_df = pd.DataFrame(
        _make_rows(
            base_tag,
            years=[2010, 2010, 2011, 2011, 2012, 2012],
            prices=[9000, 8600, 8300, 8000, 7600, 7300],
            odometers=[70000, 90000, 110000, 130000, 150000, 170000],
        )
        + _make_rows(
            alias_tag,
            years=[2010, 2010, 2011, 2011, 2012, 2012],
            prices=[9100, 8700, 8400, 8100, 7700, 7400],
            odometers=[75000, 95000, 115000, 135000, 155000, 175000],
        )
    )

    candidates = build_curve_candidates(
        tagged_df,
        curve_tags=set(),
        min_listings=10,
        max_year_span=6,
        min_odometer_std=10000,
        generated_at="2026-03-20T00:00:00Z",
    )

    assert len(candidates) == 1
    row = candidates.iloc[0]
    expected_curve_tag = curves.resolve_curve_canonical_tag(base_tag)
    assert row["curve_tag"] == expected_curve_tag
    assert row["sold_count_total"] == 12
    assert row["canonical_tag_count"] == 2
    assert row["source_canonical_tags"] == f"{alias_tag}|{base_tag}"
    assert row["recommended_action"] == "build_curve"
    assert row["next_step"] == "ai_curve_build"
    assert row["next_after_curve"] == "autotrader_scrape"
    curves.load_curve_aliases.cache_clear()


def test_build_curve_candidates_marks_existing_curve_for_refresh():
    tag = "hyundai_i30_active_petrol_auto_hatch_gd"
    curve_tag = curves.resolve_curve_canonical_tag(tag)
    tagged_df = pd.DataFrame(
        _make_rows(
            tag,
            years=[2013, 2013, 2014, 2014, 2015, 2015, 2016, 2016, 2016, 2016],
            prices=[11000, 10400, 10000, 9600, 9200, 8800, 8400, 8000, 7600, 7200],
            odometers=[50000, 70000, 90000, 110000, 130000, 150000, 170000, 190000, 210000, 230000],
        )
    )

    candidates = build_curve_candidates(
        tagged_df,
        curve_tags={curve_tag},
        min_listings=10,
        max_year_span=6,
        min_odometer_std=10000,
    )

    row = candidates.iloc[0]
    assert row["curve_tag"] == curve_tag
    assert bool(row["curve_exists"]) is True
    assert bool(row["ready_for_curve"]) is True
    assert row["recommended_action"] == "refresh_curve"
    assert row["next_step"] == "ai_curve_refresh"


def test_build_curve_candidates_sends_weak_groups_to_manual_review():
    tag = "toyota_camry_ascent_petrol_auto_sedan_asv70r"
    tagged_df = pd.DataFrame(
        _make_rows(
            tag,
            years=[2018, 2025, 2025],
            prices=[24000, 23800, 23700],
            odometers=[100000, 100500, 101000],
        )
    )

    candidates = build_curve_candidates(
        tagged_df,
        curve_tags=set(),
        min_listings=5,
        max_year_span=4,
        min_odometer_std=5000,
    )

    row = candidates.iloc[0]
    assert bool(row["ready_for_curve"]) is False
    assert row["recommended_action"] == "manual_review"
    assert row["next_step"] == "manual_review"
    assert row["next_after_curve"] == ""
    assert "low_sample_size" in row["review_reason"]
    assert "wide_year_span" in row["review_reason"]
    assert "low_odometer_variance" in row["review_reason"]


def test_build_curve_candidates_deduplicates_review_reasons_in_stable_order():
    tag = "toyota_camry_ascent_petrol_auto_sedan_asv70r"
    tagged_df = pd.DataFrame(
        _make_rows(
            tag,
            years=[2018, 2025, 2025],
            prices=[24000, 23800, 23700],
            odometers=[100000, 100500, 101000],
        )
    )

    candidates = build_curve_candidates(
        tagged_df,
        curve_tags=set(),
        min_listings=5,
        max_year_span=4,
        min_odometer_std=5000,
    )

    row = candidates.iloc[0]
    reasons = row["review_reason"].split("|")
    assert reasons == list(dict.fromkeys(reasons))
    assert reasons[0] == "wide_year_span"
    assert "low_odometer_variance" in reasons
    assert "low_sample_size" in reasons
    assert "low_active_listing_count" in reasons
    assert "low_active_year_coverage" in reasons


def test_build_curve_candidates_falls_back_when_numeric_shadow_columns_are_blank():
    tag = "toyota_corolla_ascent_petrol_auto_sedan_zre152r"
    tagged_df = pd.DataFrame(
        {
            "canonical_tag": [tag] * 5,
            "year": [2009, 2010, 2010, 2011, 2011],
            "price": [12000, 11500, 11000, 10500, 10000],
            "price_numeric": [None, None, None, None, None],
            "odometer_reading": [70000, 90000, 110000, 130000, 150000],
            "odometer_numeric": [None, None, None, None, None],
        }
    )

    candidates = build_curve_candidates(
        tagged_df,
        curve_tags=set(),
        min_listings=5,
        max_year_span=6,
        min_odometer_std=10000,
    )

    row = candidates.iloc[0]
    assert row["sold_count_usable"] == 5
    assert bool(row["ready_for_curve"]) is True
    assert row["recommended_action"] == "build_curve"


def test_build_curve_candidates_can_unlock_from_conservative_market_evidence():
    tag = "toyota_corolla_ascent_petrol_auto_sedan_zre172r"
    tagged_df = pd.DataFrame(
        _make_rows(
            tag,
            years=[2015, 2015, 2016, 2016, 2017],
            prices=[14000, 13200, 12800, 12100, 11600],
            odometers=[70000, 95000, 120000, 145000, 170000],
        )
    )
    active_df = pd.DataFrame(
        {
            "canonical_tag": [tag] * 45,
            "year": ([2015] * 15) + ([2016] * 15) + ([2017] * 15),
            "price": [15000 - (index * 40) for index in range(45)],
            "odometer": [50000 + (index * 4000) for index in range(45)],
        }
    )

    candidates = build_curve_candidates(
        tagged_df,
        active_market_df=active_df,
        curve_tags=set(),
        min_listings=20,
        min_market_sold_listings=5,
        min_active_listings=40,
        min_active_years=3,
        min_total_sold_floor=3,
        min_total_active_floor=25,
        max_year_span=6,
        min_odometer_std=10000,
    )

    row = candidates.iloc[0]
    assert row["sold_count_usable"] == 5
    assert row["active_count_usable"] == 45
    assert bool(row["passes_min_listings"]) is False
    assert bool(row["passes_market_support"]) is True
    assert bool(row["ready_for_curve"]) is True
    assert row["readiness_source"] == "market_evidence"
    assert row["recommended_action"] == "build_curve"


def test_build_curve_candidates_keeps_very_thin_groups_in_manual_review_even_with_active_market():
    tag = "toyota_camry_ascent_petrol_auto_sedan_asv70r"
    tagged_df = pd.DataFrame(
        _make_rows(
            tag,
            years=[2018, 2018],
            prices=[23000, 22500],
            odometers=[100000, 120000],
        )
    )
    active_df = pd.DataFrame(
        {
            "canonical_tag": [tag] * 60,
            "year": ([2018] * 20) + ([2019] * 20) + ([2020] * 20),
            "price": [26000 - (index * 50) for index in range(60)],
            "odometer": [30000 + (index * 3500) for index in range(60)],
        }
    )

    candidates = build_curve_candidates(
        tagged_df,
        active_market_df=active_df,
        curve_tags=set(),
        min_listings=20,
        min_market_sold_listings=5,
        min_active_listings=40,
        min_active_years=3,
        min_total_sold_floor=3,
        min_total_active_floor=25,
        max_year_span=6,
        min_odometer_std=10000,
    )

    row = candidates.iloc[0]
    assert bool(row["ready_for_curve"]) is False
    assert row["recommended_action"] == "manual_review"
    assert "very_low_total_evidence" in row["review_reason"] or "low_sample_size" in row["review_reason"]
