from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_assign_canonical_tag_accepts_ford_territory_sz_tx_ts_diesel_auto_suv():
    _load_curve_year_band.cache_clear()
    tx_row = {
        "make": "Ford",
        "model": "Territory",
        "variant": "TX SZ turbo diesel automatic 7 seats wagon",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2013",
        "price": "1200",
        "url": "https://www.example.com/2013-ford-territory-tx-sz-turbo-diesel-automatic-7-seats-wagon",
    }
    ts_row = {
        **tx_row,
        "variant": "TS AWD SZ MkII diesel automatic SUV",
        "body_type": "SUV",
        "year": "2016",
        "url": "https://www.example.com/2016-ford-territory-ts-awd-sz-mkii-diesel-automatic-suv",
    }
    petrol_row = {
        **tx_row,
        "variant": "TX SZ petrol automatic SUV",
        "fuel_type": "Petrol",
        "url": "https://www.example.com/2013-ford-territory-tx-sz-petrol-automatic-suv",
    }
    manual_row = {
        **tx_row,
        "variant": "TX SZ turbo diesel manual SUV",
        "transmission": "Manual",
        "url": "https://www.example.com/2013-ford-territory-tx-sz-turbo-diesel-manual-suv",
    }

    assert assign_canonical_tag(tx_row, require_price=True)[0:2] == (
        "ford_territory_tx-ts_diesel_auto_suv_sz",
        "[OK]",
    )
    assert assign_canonical_tag(ts_row, require_price=True)[0:2] == (
        "ford_territory_tx-ts_diesel_auto_suv_sz",
        "[OK]",
    )
    assert assign_canonical_tag(petrol_row, require_price=True)[0:2] == (
        "ford_territory_tx-ts_petrol_auto_suv_sz",
        "[OK]",
    )
    assert assign_canonical_tag(manual_row, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_accepts_ford_territory_petrol_family_lanes():
    _load_curve_year_band.cache_clear()
    sy_row = {
        "make": "Ford",
        "model": "Territory",
        "variant": "TS SY MkII automatic petrol SUV",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol - Unleaded ULP",
        "year": "2010",
        "price": "6500",
        "url": "https://www.example.com/2010-ford-territory-ts-sy-mkii-auto-petrol-wagon",
    }
    sz_row = {
        **sy_row,
        "variant": "TX SZ MkII petrol automatic SUV",
        "year": "2016",
        "url": "https://www.example.com/2016-ford-territory-tx-sz-mkii-auto-petrol-suv",
    }
    titanium_row = {
        **sz_row,
        "variant": "Titanium SZ petrol automatic SUV",
        "url": "https://www.example.com/2015-ford-territory-titanium-sz-auto-petrol-suv",
    }
    turbo_row = {
        **sy_row,
        "variant": "Turbo Ghia SY automatic petrol SUV",
        "url": "https://www.example.com/2007-ford-territory-turbo-ghia-sy-auto-petrol-suv",
    }
    diesel_row = {
        **sz_row,
        "variant": "TX SZ diesel automatic SUV",
        "fuel_type": "Diesel",
        "url": "https://www.example.com/2013-ford-territory-tx-sz-diesel-auto-suv",
    }

    assert assign_canonical_tag(sy_row, require_price=True)[0:2] == (
        "ford_territory_tx-ts-ghia_petrol_auto_suv_sy",
        "[OK]",
    )
    assert assign_canonical_tag(sz_row, require_price=True)[0:2] == (
        "ford_territory_tx-ts_petrol_auto_suv_sz",
        "[OK]",
    )
    assert assign_canonical_tag(titanium_row, require_price=True)[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(turbo_row, require_price=True)[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(diesel_row, require_price=True)[0] != (
        "ford_territory_tx-ts_petrol_auto_suv_sz"
    )


def test_assign_canonical_tag_accepts_falcon_xr6_fg_auto_petrol_sedan_only():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Ford",
        "model": "Falcon",
        "variant": "XR6 FG Auto",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol - Unleaded ULP",
        "year": "2010",
        "price": "15000",
        "url": "https://www.example.com/2010-ford-falcon-xr6-fg-auto-sedan",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "ford_falcon_xr6_petrol_auto_sedan_fg",
        "[OK]",
    )

    rejected_rows = [
        {**base_row, "variant": "XR6 Turbo FG Auto"},
        {**base_row, "transmission": "Manual", "variant": "XR6 FG Manual"},
        {**base_row, "body_type": "Ute", "variant": "XR6 FG Auto Ute"},
        {**base_row, "variant": "XR6 FG-X Auto", "year": "2015"},
    ]
    for row in rejected_rows:
        assert assign_canonical_tag(row, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_splits_falcon_xr6_fg_mkii_by_year():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Ford",
        "model": "Falcon",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol - Unleaded ULP",
        "price": "12000",
    }

    assert assign_canonical_tag(
        {
            **base_row,
            "variant": "XR6 FG MkII Auto",
            "series": "FG MkII",
            "year": "2013",
            "url": "https://example.test/falcon-fg-mkii",
        },
        require_price=True,
    )[0:2] == ("ford_falcon_xr6_petrol_auto_sedan_fgmkii", "[OK]")

    assert assign_canonical_tag(
        {
            **base_row,
            "variant": "XR6 FG Auto",
            "series": "FG",
            "year": "2010",
            "url": "https://example.test/falcon-fg",
        },
        require_price=True,
    )[0:2] == ("ford_falcon_xr6_petrol_auto_sedan_fg", "[OK]")


def test_assign_canonical_tag_accepts_everest_trend_ua_4wd_only():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Ford",
        "model": "Everest",
        "variant": "Trend UA Auto 4WD",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2017",
        "price": "27000",
        "url": "https://www.example.com/2017-ford-everest-trend-ua-auto-4wd",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "ford_everest_trend_diesel_auto_suv_ua",
        "[OK]",
    )

    rejected_rows = [
        {**base_row, "variant": "Trend UA Auto RWD"},
        {**base_row, "variant": "Trend UA II Auto 4WD", "year": "2020"},
        {**base_row, "variant": "Sport UA Auto 4WD"},
        {**base_row, "transmission": "Manual", "variant": "Trend UA Manual 4WD"},
    ]
    for row in rejected_rows:
        assert assign_canonical_tag(row, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_accepts_ranger_wildtrak_20_px_mkiii_only():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Ford",
        "model": "Ranger",
        "variant": "Wildtrak 2.0 (4X4)",
        "body_type": "Double Cab Pick Up",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2020",
        "price": "41000",
        "url": "https://www.example.com/2020-ford-ranger-wildtrak-2-0-4x4",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "ford_ranger_wildtrak-2.0_diesel_auto_ute_px-mkiii",
        "[OK]",
    )

    rejected_rows = [
        {**base_row, "variant": "Wildtrak 3.2 (4X4)"},
        {**base_row, "variant": "Wildtrak 3.0 (4X4)", "year": "2023"},
        {**base_row, "variant": "Wildtrak 2.0 FullTime 4WD DR MY24", "year": "2024"},
        {**base_row, "variant": "Wildtrak X 2.0 (4X4)"},
        {**base_row, "transmission": "Manual"},
    ]
    for row in rejected_rows:
        assert assign_canonical_tag(row, require_price=True)[0] == "UNCLASSIFIED"
