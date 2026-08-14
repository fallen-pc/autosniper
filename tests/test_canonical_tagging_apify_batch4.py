from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_apify_batch4_lanes_stay_trim_generation_body_and_powertrain_specific():
    _load_curve_year_band.cache_clear()
    cases = [
        ({"make": "Ford", "model": "Kuga", "variant": "AWD Trend TF", "body_type": "Wagon", "transmission": "Automatic", "fuel_type": "Diesel", "year": "2013", "price": "8000", "url": "https://example.test/kuga-trend"}, "ford_kuga_awd-trend_diesel_auto_wagon_tf", [{"variant": "AWD Titanium TF"}, {"variant": "AWD Trend TF MkII", "year": "2015"}, {"fuel_type": "Petrol"}, {"transmission": "Manual"}]),
        ({"make": "Ford", "model": "Kuga", "variant": "AWD Titanium TF", "body_type": "Wagon", "transmission": "Automatic", "fuel_type": "Diesel", "year": "2014", "price": "9000", "url": "https://example.test/kuga-titanium"}, "ford_kuga_awd-titanium_diesel_auto_wagon_tf", [{"variant": "AWD Trend TF"}, {"variant": "AWD Titanium TF MkII", "year": "2015"}, {"fuel_type": "Petrol"}, {"transmission": "Manual"}]),
        ({"make": "Mazda", "model": "3", "variant": "Neo BL", "body_type": "Sedan", "transmission": "Automatic", "fuel_type": "Petrol", "year": "2012", "price": "9000", "url": "https://example.test/mazda3-neo-bl-sedan"}, "mazda_3_neo_petrol_auto_sedan_bl", [{"body_type": "Hatchback"}, {"variant": "Maxx BL"}, {"variant": "Neo BK", "year": "2008"}, {"transmission": "Manual"}]),
        ({"make": "Holden", "model": "Barina", "variant": "TK", "body_type": "Hatchback", "transmission": "Manual", "fuel_type": "Petrol", "year": "2010", "price": "4000", "url": "https://example.test/barina-tk-manual"}, "holden_barina_tk_petrol_manual_hatch", [{"body_type": "Sedan"}, {"variant": "TM", "year": "2012"}, {"transmission": "Automatic"}, {"fuel_type": "Diesel"}]),
    ]
    for base_row, expected, changes in cases:
        assert assign_canonical_tag(base_row, require_price=True)[0:2] == (expected, "[OK]")
        for change in changes:
            assert assign_canonical_tag({**base_row, **change}, require_price=True)[0] != expected
