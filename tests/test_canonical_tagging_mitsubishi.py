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
