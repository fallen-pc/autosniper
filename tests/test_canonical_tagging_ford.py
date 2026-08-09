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
