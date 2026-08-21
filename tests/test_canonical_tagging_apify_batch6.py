"""Regression coverage for the exact Carsales/Grays lanes published in batch 6."""

from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_apify_batch6_lanes_match_without_absorbing_adjacent_vehicles():
    _load_curve_year_band.cache_clear()
    cases = [
        (
            {"make": "Ford", "model": "Kuga", "variant": "AWD Ambiente TF", "body_type": "Wagon",
             "transmission": "Automatic", "fuel_type": "Petrol", "year": "2013", "price": "8000",
             "url": "https://example.test/kuga-ambiente-tf"},
            "ford_kuga_awd-ambiente_petrol_auto_wagon_tf",
            [{"variant": "AWD Trend TF"}, {"fuel_type": "Diesel"},
             {"variant": "2WD Ambiente TF MkII", "year": "2015"}],
        ),
        (
            {"make": "Holden", "model": "Barina", "variant": "TK", "body_type": "Hatchback",
             "transmission": "Automatic", "fuel_type": "Petrol", "year": "2010", "price": "4500",
             "url": "https://example.test/barina-tk-auto"},
            "holden_barina_tk_petrol_auto_hatch",
            [{"body_type": "Sedan"}, {"transmission": "Manual"},
             {"variant": "CD TM", "year": "2013"}],
        ),
        (
            {"make": "Volkswagen", "model": "Golf", "variant": "103TSI Highline A7",
             "body_type": "Hatchback", "transmission": "Automatic", "fuel_type": "Petrol",
             "year": "2014", "price": "9500", "url": "https://example.test/golf-highline-a7"},
            "volkswagen_golf_103tsi-highline_petrol_auto_hatch_a7",
            [{"variant": "110TSI Highline A7"}, {"body_type": "Wagon"}, {"fuel_type": "Diesel"}],
        ),
    ]
    for base_row, expected, changes in cases:
        assert assign_canonical_tag(base_row, require_price=True)[0:2] == (expected, "[OK]")
        for change in changes:
            assert assign_canonical_tag({**base_row, **change}, require_price=True)[0] != expected
