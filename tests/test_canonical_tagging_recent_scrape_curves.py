from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_assign_canonical_tag_accepts_kluger_kxr_gsu40r_only():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Toyota",
        "model": "Kluger",
        "variant": "KX-R GSU40R Auto 2WD",
        "body_type": "SUV",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2010",
        "price": "9000",
        "url": "https://www.example.com/2010-toyota-kluger-kx-r-gsu40r-auto-suv",
    }
    kxs_row = {
        **row,
        "variant": "KX-S GSU40R Auto",
        "url": "https://www.example.com/2010-toyota-kluger-kx-s-gsu40r-auto-suv",
    }
    awd_row = {
        **row,
        "variant": "KX-R GSU45R Auto AWD",
        "url": "https://www.example.com/2010-toyota-kluger-kx-r-gsu45r-auto-suv",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (
        "toyota_kluger_kx-r_petrol_auto_suv_gsu40r",
        "[OK]",
    )
    assert assign_canonical_tag(kxs_row, require_price=True)[0:2] == (
        "toyota_kluger_kx-s_petrol_auto_suv_gsu40r",
        "[OK]",
    )
    assert assign_canonical_tag(awd_row, require_price=True)[0:2] == (
        "toyota_kluger_kx-r_petrol_auto_suv_gsu45r",
        "[OK]",
    )


def test_assign_canonical_tag_accepts_outlander_ls_zh_only():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Mitsubishi",
        "model": "Outlander",
        "variant": "LS ZH CVT Wagon",
        "body_type": "SUV",
        "transmission": "CVT",
        "fuel_type": "Petrol",
        "year": "2011",
        "price": "8000",
        "url": "https://www.example.com/2011-mitsubishi-outlander-ls-zh-cvt-suv",
    }
    es_row = {
        **row,
        "variant": "ES ZH CVT Wagon",
        "url": "https://www.example.com/2011-mitsubishi-outlander-es-zh-cvt-suv",
    }
    diesel_row = {
        **row,
        "fuel_type": "Diesel",
        "url": "https://www.example.com/2011-mitsubishi-outlander-ls-zh-diesel-auto-suv",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (
        "mitsubishi_outlander_ls_petrol_auto_suv_zh",
        "[OK]",
    )
    assert assign_canonical_tag(es_row, require_price=True)[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(diesel_row, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_accepts_xtrail_st_t31_only():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Nissan",
        "model": "X-Trail",
        "variant": "ST T31 CVT",
        "body_type": "SUV",
        "transmission": "CVT",
        "fuel_type": "Petrol",
        "year": "2012",
        "price": "8500",
        "url": "https://www.example.com/2012-nissan-x-trail-st-t31-cvt-suv",
    }
    stl_row = {
        **row,
        "variant": "ST-L T31 CVT",
        "url": "https://www.example.com/2012-nissan-x-trail-st-l-t31-cvt-suv",
    }
    diesel_row = {
        **row,
        "variant": "TS T31 Diesel Auto",
        "fuel_type": "Diesel",
        "url": "https://www.example.com/2012-nissan-x-trail-ts-t31-diesel-auto-suv",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (
        "nissan_xtrail_st_petrol_auto_suv_t31",
        "[OK]",
    )
    assert assign_canonical_tag(stl_row, require_price=True)[0:2] == (
        "nissan_xtrail_st-l_petrol_auto_suv_t31",
        "[OK]",
    )
    assert assign_canonical_tag(diesel_row, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_accepts_forester_x_s3_only():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Subaru",
        "model": "Forester",
        "variant": "X S3 Auto AWD",
        "body_type": "SUV",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2010",
        "price": "6500",
        "url": "https://www.example.com/2010-subaru-forester-x-s3-auto-suv",
    }
    xs_row = {
        **row,
        "variant": "XS S3 Auto AWD",
        "url": "https://www.example.com/2010-subaru-forester-xs-s3-auto-suv",
    }
    diesel_row = {
        **row,
        "variant": "2.0D S3 Auto",
        "fuel_type": "Diesel",
        "url": "https://www.example.com/2010-subaru-forester-2-0d-s3-auto-suv",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (
        "subaru_forester_x_petrol_auto_suv_s3",
        "[OK]",
    )
    assert assign_canonical_tag(xs_row, require_price=True)[0:2] == (
        "subaru_forester_xs_petrol_auto_suv_s3",
        "[OK]",
    )
    assert assign_canonical_tag(diesel_row, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_accepts_second_batch_same_lane_rows():
    _load_curve_year_band.cache_clear()
    rows = [
        (
            {
                "make": "Toyota",
                "model": "Kluger",
                "variant": "KX-S GSU45R Auto AWD",
                "body_type": "SUV",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2011",
                "price": "11200",
                "url": "https://www.example.com/2011-toyota-kluger-kx-s-gsu45r-auto-suv",
            },
            "toyota_kluger_kx-s_petrol_auto_suv_gsu45r",
        ),
        (
            {
                "make": "Toyota",
                "model": "Kluger",
                "variant": "Grande GSU45R Auto AWD",
                "body_type": "SUV",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2013",
                "price": "12000",
                "url": "https://www.example.com/2013-toyota-kluger-grande-gsu45r-auto-suv",
            },
            "toyota_kluger_grande_petrol_auto_suv_gsu45r",
        ),
        (
            {
                "make": "Mitsubishi",
                "model": "Outlander",
                "variant": "ES ZJ CVT Wagon",
                "body_type": "SUV",
                "transmission": "CVT",
                "fuel_type": "Petrol",
                "year": "2014",
                "price": "9000",
                "url": "https://www.example.com/2014-mitsubishi-outlander-es-zj-cvt-suv",
            },
            "mitsubishi_outlander_es_petrol_auto_suv_zj",
        ),
        (
            {
                "make": "Mitsubishi",
                "model": "Outlander",
                "variant": "LS ZK CVT Wagon",
                "body_type": "SUV",
                "transmission": "CVT",
                "fuel_type": "Petrol",
                "year": "2016",
                "price": "13000",
                "url": "https://www.example.com/2016-mitsubishi-outlander-ls-zk-cvt-suv",
            },
            "mitsubishi_outlander_ls_petrol_auto_suv_zk",
        ),
        (
            {
                "make": "Nissan",
                "model": "X-Trail",
                "variant": "Ti T31 CVT",
                "body_type": "SUV",
                "transmission": "CVT",
                "fuel_type": "Petrol",
                "year": "2010",
                "price": "8500",
                "url": "https://www.example.com/2010-nissan-x-trail-ti-t31-cvt-suv",
            },
            "nissan_xtrail_ti_petrol_auto_suv_t31",
        ),
    ]

    for row, expected_tag in rows:
        assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")
