from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_assign_canonical_tag_accepts_mitsubishi_pajero_glx_nt_nw_diesel_auto_only():
    _load_curve_year_band.cache_clear()
    nt_row = {
        "make": "Mitsubishi",
        "model": "Pajero",
        "variant": "GLX NT turbo diesel automatic 7 seats wagon",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2010",
        "price": "1200",
        "url": "https://www.example.com/2010-mitsubishi-pajero-glx-nt-turbo-diesel-automatic-wagon",
    }
    nw_row = {
        **nt_row,
        "variant": "GLX NW diesel auto 4x4 SUV",
        "body_type": "SUV",
        "year": "2013",
        "url": "https://www.example.com/2013-mitsubishi-pajero-glx-nw-diesel-auto-4x4-suv",
    }
    exceed_row = {
        **nt_row,
        "variant": "Exceed NT turbo diesel automatic wagon",
        "url": "https://www.example.com/2009-mitsubishi-pajero-exceed-nt-turbo-diesel-automatic-wagon",
    }
    petrol_row = {
        **nt_row,
        "variant": "GLX NT petrol automatic wagon",
        "fuel_type": "Petrol",
        "url": "https://www.example.com/2010-mitsubishi-pajero-glx-nt-petrol-automatic-wagon",
    }

    assert assign_canonical_tag(nt_row, require_price=True)[0:2] == (
        "mitsubishi_pajero_glx_diesel_auto_suv_nt-nw",
        "[OK]",
    )
    assert assign_canonical_tag(nw_row, require_price=True)[0:2] == (
        "mitsubishi_pajero_glx_diesel_auto_suv_nt-nw",
        "[OK]",
    )
    assert assign_canonical_tag(exceed_row, require_price=True)[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(petrol_row, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_keeps_pajero_sport_qe_out_of_pajero_nx_lanes():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Mitsubishi",
        "model": "Pajero",
        "body_type": "SUV",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2018",
        "price": "25000",
    }

    for badge in ("GLX", "GLS", "Exceed"):
        sport_row = {
            **base_row,
            "variant": f"Pajero Sport {badge} QE diesel automatic SUV",
            "url": f"https://www.example.com/2018-mitsubishi-pajero-sport-{badge.lower()}-qe",
        }
        nx_row = {
            **base_row,
            "variant": f"{badge} NX diesel automatic SUV",
            "url": f"https://www.example.com/2018-mitsubishi-pajero-{badge.lower()}-nx",
        }

        assert assign_canonical_tag(sport_row, require_price=True)[0] == "UNCLASSIFIED"
        assert assign_canonical_tag(nx_row, require_price=True)[0:2] == (
            f"mitsubishi_pajero_{badge.lower()}_diesel_auto_suv_nx",
            "[OK]",
        )


def test_assign_canonical_tag_accepts_mitsubishi_triton_glx_mn_manual_only():
    _load_curve_year_band.cache_clear()
    glx_manual = {
        "make": "Mitsubishi",
        "model": "Triton",
        "variant": "GLX MN turbo diesel manual dual cab",
        "body_type": "Dual Cab",
        "transmission": "Manual",
        "fuel_type": "Diesel",
        "year": "2014",
        "price": "1200",
        "url": "https://www.example.com/2014-mitsubishi-triton-glx-mn-turbo-diesel-manual-dual-cab",
    }
    glxr_manual = {
        **glx_manual,
        "variant": "GLX-R MN turbo diesel manual pick up",
        "url": "https://www.example.com/2014-mitsubishi-triton-glx-r-mn-turbo-diesel-manual-pick-up",
    }
    auto_row = {
        **glx_manual,
        "variant": "GLX MN turbo diesel automatic dual cab",
        "transmission": "Automatic",
        "url": "https://www.example.com/2014-mitsubishi-triton-glx-mn-turbo-diesel-automatic-dual-cab",
    }
    mq_row = {
        **glx_manual,
        "variant": "GLX MQ turbo diesel manual dual cab",
        "url": "https://www.example.com/2016-mitsubishi-triton-glx-mq-turbo-diesel-manual-dual-cab",
    }

    assert assign_canonical_tag(glx_manual, require_price=True)[0:2] == (
        "mitsubishi_triton_glx_diesel_manual_ute_mn",
        "[OK]",
    )
    assert assign_canonical_tag(glxr_manual, require_price=True)[0:2] == (
        "mitsubishi_triton_glxr_diesel_manual_ute_mn",
        "[OK]",
    )
    assert assign_canonical_tag(auto_row, require_price=True)[0:2] == (
        "mitsubishi_triton_glx_diesel_auto_ute_mn",
        "[OK]",
    )
    assert assign_canonical_tag(mq_row, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_accepts_mitsubishi_triton_gl_r_aliases_as_glxr():
    _load_curve_year_band.cache_clear()

    manual_row = {
        "make": "Mitsubishi",
        "model": "Triton",
        "variant": "GL-R MN Manual 4x4 MY12 Double Cab",
        "body_type": "Ute",
        "transmission": "Manual",
        "fuel_type": "Diesel",
        "year": "2012",
        "price": "12000",
        "url": "https://www.example.com/2012-mitsubishi-triton-gl-r-mn-manual-diesel-ute",
    }
    auto_row = {
        **manual_row,
        "variant": "GL-R MN Auto 4x4 MY12 Double Cab",
        "transmission": "Automatic",
        "url": "https://www.example.com/2012-mitsubishi-triton-gl-r-mn-auto-diesel-ute",
    }

    assert assign_canonical_tag(manual_row, require_price=True)[0:2] == (
        "mitsubishi_triton_glxr_diesel_manual_ute_mn",
        "[OK]",
    )
    assert assign_canonical_tag(auto_row, require_price=True)[0:2] == (
        "mitsubishi_triton_glxr_diesel_auto_ute_mn",
        "[OK]",
    )


def test_assign_canonical_tag_splits_outlander_es_zl_by_drivetrain():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Mitsubishi",
        "model": "Outlander",
        "badge": "ES",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2019",
        "price": "20000",
    }
    cases = [
        (
            {**base_row, "variant": "ES ZL Auto 2WD", "url": "https://example.test/outlander-zl-2wd"},
            "mitsubishi_outlander_es-2wd_petrol_auto_suv_zl",
        ),
        (
            {**base_row, "variant": "ES ZL Auto AWD", "url": "https://example.test/outlander-zl-awd"},
            "mitsubishi_outlander_es-awd_petrol_auto_suv_zl",
        ),
    ]
    for row, expected_tag in cases:
        assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")

    rejected_rows = [
        {**base_row, "variant": "LS ZL Auto 2WD", "badge": "LS", "url": "https://example.test/outlander-ls"},
        {**base_row, "variant": "ES ZL Auto 2WD PHEV", "fuel_type": "Hybrid", "url": "https://example.test/outlander-phev"},
    ]
    for row in rejected_rows:
        assert assign_canonical_tag(row, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_supports_outlander_es_zm_2wd_only():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Mitsubishi",
        "model": "Outlander",
        "badge": "ES",
        "body_type": "SUV",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2022",
        "price": "26900",
    }

    assert assign_canonical_tag(
        {
            **base_row,
            "variant": "ES ZM Auto 2WD MY22",
            "url": "https://example.test/outlander-zm-2wd",
        },
        require_price=True,
    )[0:2] == ("mitsubishi_outlander_es-2wd_petrol_auto_suv_zm", "[OK]")

    assert assign_canonical_tag(
        {
            **base_row,
            "variant": "ES ZM Auto AWD MY22",
            "url": "https://example.test/outlander-zm-awd",
        },
        require_price=True,
    )[0] == "UNCLASSIFIED"
