from __future__ import annotations

from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_assign_canonical_tag_accepts_hyundai_gd_2012_active_into_early_curve():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Hyundai",
        "model": "i30",
        "variant": "Active Auto F",
        "series": "gd",
        "body_type": "hatchback",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2012",
        "price": "14800",
        "url": "https://www.example.com/hyundai/i30/active-2012",
    }

    canonical_tag, canonical_reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "hyundai_i30_active_petrol_auto_hatch_gd"
    assert canonical_reason == "[OK]"


def test_assign_canonical_tag_rejects_hyundai_gd_elite_from_active_curve():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Hyundai",
        "model": "i30",
        "variant": "Elite Auto F MY14",
        "series": "gd",
        "body_type": "hatchback",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2013",
        "price": "13200",
        "url": "https://www.example.com/hyundai/i30/elite",
    }

    canonical_tag, canonical_reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "UNCLASSIFIED"
    assert canonical_reason in {"[AMBIG_BADGE]", "[DISALLOWED_VARIANT]"}


def test_assign_canonical_tag_rejects_hyundai_gd_active_x_from_early_curve():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Hyundai",
        "model": "i30",
        "variant": "Active X Auto F MY16",
        "series": "gd",
        "body_type": "hatchback",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2015",
        "price": "14500",
        "url": "https://www.example.com/hyundai/i30/active-x",
    }

    canonical_tag, canonical_reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "UNCLASSIFIED"
    assert canonical_reason in {"[DISALLOWED_VARIANT]", "[OUT_OF_SCOPE_YEAR]"}


def test_assign_canonical_tag_accepts_hyundai_pd_active_into_pd_curve():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Hyundai",
        "model": "i30",
        "variant": "Active Auto F MY20",
        "series": "pd2",
        "body_type": "hatchback",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2019",
        "price": "19500",
        "url": "https://www.example.com/hyundai/i30/pd-active",
    }

    canonical_tag, canonical_reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "hyundai_i30_active_petrol_auto_hatch_pd"
    assert canonical_reason == "[OK]"


def test_assign_canonical_tag_rejects_hyundai_pd_active_x_from_active_curve():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Hyundai",
        "model": "i30",
        "variant": "Active X Auto F MY20",
        "series": "pd2",
        "body_type": "hatchback",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2019",
        "price": "18500",
        "url": "https://www.example.com/hyundai/i30/pd-active-x",
    }

    canonical_tag, canonical_reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "UNCLASSIFIED"
    assert canonical_reason == "[DISALLOWED_VARIANT]"


def test_assign_canonical_tag_rejects_hyundai_active_gd_from_pd_curve():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Hyundai",
        "model": "i30",
        "variant": "Active GD",
        "body_type": "hatchback",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2017",
        "price": "10200",
        "url": "https://www.example.com/hyundai/i30/2017-active-gd-automatic-hatchback",
    }

    canonical_tag, canonical_reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "UNCLASSIFIED"
    assert canonical_reason in {"[DISALLOWED_VARIANT]", "[OUT_OF_SCOPE_YEAR]"}


def test_assign_canonical_tag_accepts_hyundai_ix35_se_lm_lane():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Hyundai",
        "model": "ix35",
        "variant": "SE FWD LM",
        "body_type": "wagon",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2014",
        "price": "4300",
        "url": "https://www.example.com/2014-hyundai-ix35-se-fwd-lm-automatic-wagon",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (
        "hyundai_ix35_se_petrol_auto_wagon_lm",
        "[OK]",
    )


def test_assign_canonical_tag_accepts_hyundai_ix35_elite_lm_lane():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Hyundai",
        "model": "ix35",
        "variant": "Elite FWD LM",
        "body_type": "wagon",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2014",
        "price": "109",
        "url": "https://www.example.com/2014-hyundai-ix35-elite-fwd-lm-automatic-wagon",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (
        "hyundai_ix35_elite_petrol_auto_wagon_lm",
        "[OK]",
    )


def test_assign_canonical_tag_accepts_hyundai_getz_sx_tb_auto_and_manual_lanes():
    _load_curve_year_band.cache_clear()
    auto_row = {
        "make": "Hyundai",
        "model": "Getz",
        "variant": "SX TB",
        "body_type": "hatchback",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2009",
        "price": "1009",
        "url": "https://www.example.com/2009-hyundai-getz-sx-tb-automatic-hatchback",
    }
    manual_row = {
        "make": "Hyundai",
        "model": "Getz",
        "variant": "SX TB",
        "body_type": "hatchback",
        "transmission": "manual",
        "fuel_type": "petrol",
        "year": "2008",
        "price": "9",
        "url": "https://www.example.com/2008-hyundai-getz-sx-tb-manual-hatchback",
    }

    assert assign_canonical_tag(auto_row, require_price=True)[0:2] == (
        "hyundai_getz_sx_petrol_auto_hatch_tb",
        "[OK]",
    )
    assert assign_canonical_tag(manual_row, require_price=True)[0:2] == (
        "hyundai_getz_sx_petrol_manual_hatch_tb",
        "[OK]",
    )


def test_assign_canonical_tag_accepts_hyundai_accent_active_rb_auto_hatch_only():
    _load_curve_year_band.cache_clear()
    auto_hatch = {
        "make": "Hyundai",
        "model": "Accent",
        "variant": "Active RB CVT Hatchback",
        "body_type": "hatchback",
        "transmission": "CVT",
        "fuel_type": "petrol",
        "year": "2016",
        "price": "3000",
        "url": "https://www.example.com/2016-hyundai-accent-active-rb-cvt-hatchback",
    }
    manual_hatch = {
        **auto_hatch,
        "transmission": "manual",
        "url": "https://www.example.com/2016-hyundai-accent-active-rb-manual-hatchback",
    }
    auto_sedan = {
        **auto_hatch,
        "body_type": "sedan",
        "url": "https://www.example.com/2016-hyundai-accent-active-rb-cvt-sedan",
    }

    assert assign_canonical_tag(auto_hatch, require_price=True)[0:2] == (
        "hyundai_accent_active_petrol_auto_hatch_rb",
        "[OK]",
    )
    assert assign_canonical_tag(manual_hatch, require_price=True)[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(auto_sedan, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_accepts_hyundai_iload_tq_auto_diesel_van_only():
    _load_curve_year_band.cache_clear()
    auto_van = {
        "make": "Hyundai",
        "model": "iLoad",
        "variant": "TQ Turbo Diesel Van",
        "body_type": "van",
        "transmission": "automatic",
        "fuel_type": "diesel",
        "year": "2014",
        "price": "9500",
        "url": "https://www.example.com/2014-hyundai-iload-tq-turbo-diesel-automatic-van",
    }
    manual_van = {
        **auto_van,
        "transmission": "manual",
        "url": "https://www.example.com/2014-hyundai-iload-tq-turbo-diesel-manual-van",
    }
    crew_van = {
        **auto_van,
        "variant": "TQ Crew Van Turbo Diesel",
        "url": "https://www.example.com/2014-hyundai-iload-tq-crew-van-automatic-diesel",
    }
    imax = {
        **auto_van,
        "variant": "iMax TQ Turbo Diesel",
        "url": "https://www.example.com/2014-hyundai-imax-tq-automatic-diesel",
    }

    assert assign_canonical_tag(auto_van, require_price=True)[0:2] == (
        "hyundai_iload_tq_van_auto_diesel",
        "[OK]",
    )
    assert assign_canonical_tag(manual_van, require_price=True)[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(crew_van, require_price=True)[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(imax, require_price=True)[0] == "UNCLASSIFIED"
