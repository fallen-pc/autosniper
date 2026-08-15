from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_apify_batch5_lanes_stay_trim_generation_body_and_powertrain_specific():
    _load_curve_year_band.cache_clear()
    cases = [
        ({"make": "Hyundai", "model": "i45", "variant": "Active YF", "body_type": "Sedan", "transmission": "Automatic", "fuel_type": "Petrol", "year": "2011", "price": "8000", "url": "https://example.test/i45-active"}, "hyundai_i45_active_petrol_auto_sedan_yf", [{"variant": "Premium YF"}, {"transmission": "Manual"}, {"fuel_type": "Diesel"}]),
        ({"make": "Nissan", "model": "Dualis", "variant": "ST J10", "body_type": "Wagon", "transmission": "CVT", "fuel_type": "Petrol", "year": "2011", "price": "7500", "url": "https://example.test/dualis-st"}, "nissan_dualis_st_petrol_cvt_wagon_j10", [{"variant": "+2 ST J10"}, {"variant": "Ti J10"}, {"transmission": "Manual"}, {"fuel_type": "Diesel"}]),
        ({"make": "Ford", "model": "Mondeo", "variant": "LX TDCi MC", "body_type": "Wagon", "transmission": "Automatic", "fuel_type": "Diesel", "year": "2013", "price": "5000", "url": "https://example.test/mondeo-lx"}, "ford_mondeo_lx-tdci_diesel_auto_wagon_mc", [{"variant": "Ambiente MC"}, {"body_type": "Hatchback"}, {"fuel_type": "Petrol"}, {"variant": "LX TDCi MD", "year": "2015"}]),
        ({"make": "Volkswagen", "model": "Golf", "variant": "GTI VI", "body_type": "Hatchback", "transmission": "Automatic", "fuel_type": "Petrol", "year": "2011", "price": "11000", "url": "https://example.test/golf-gti-vi"}, "volkswagen_golf_gti_petrol_auto_hatch_vi", [{"variant": "GTI V", "year": "2008"}, {"variant": "GTI VII", "year": "2014"}, {"transmission": "Manual"}, {"variant": "R VI"}]),
        ({"make": "Volvo", "model": "XC60", "variant": "T5 DZ", "body_type": "Wagon", "transmission": "Automatic", "fuel_type": "Petrol", "year": "2012", "price": "10000", "url": "https://example.test/xc60-t5"}, "volvo_xc60_t5_petrol_auto_wagon_dz", [{"variant": "T5 Teknik DZ"}, {"variant": "T5 Luxury DZ"}, {"variant": "T5 UZ", "year": "2019"}, {"fuel_type": "Diesel"}]),
    ]
    for base_row, expected, changes in cases:
        assert assign_canonical_tag(base_row, require_price=True)[0:2] == (expected, "[OK]")
        for change in changes:
            assert assign_canonical_tag({**base_row, **change}, require_price=True)[0] != expected
