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
    assert assign_canonical_tag(petrol_row, require_price=True)[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(manual_row, require_price=True)[0] == "UNCLASSIFIED"
