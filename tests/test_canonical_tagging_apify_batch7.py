"""Regression coverage for the exact Carsales/Grays lanes published in batch 7."""

from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_apify_batch7_lanes_match_without_absorbing_adjacent_vehicles():
    _load_curve_year_band.cache_clear()
    cases = [
        (
            {"make": "Hyundai", "model": "i30", "variant": "SX FD", "body_type": "Hatchback",
             "transmission": "Manual", "fuel_type": "Petrol", "year": "2011", "price": "5500",
             "url": "https://example.test/i30-sx-fd-manual"},
            "hyundai_i30_sx_petrol_manual_hatch_fd",
            [{"transmission": "Automatic"}, {"fuel_type": "Diesel"},
             {"variant": "Elite GD", "year": "2013"}],
        ),
        (
            {"make": "Toyota", "model": "Camry", "variant": "CSi SXV20R", "body_type": "Sedan",
             "transmission": "Automatic", "fuel_type": "Petrol", "year": "2001", "price": "3500",
             "url": "https://example.test/camry-csi-sxv20r"},
            "toyota_camry_csi_petrol_auto_sedan_sxv20r",
            [{"body_type": "Wagon"}, {"transmission": "Manual"},
             {"variant": "Sportivo ACV40R", "year": "2008"}],
        ),
        (
            {"make": "Ford", "model": "Falcon", "variant": "XT BA", "body_type": "Sedan",
             "transmission": "Automatic", "fuel_type": "Petrol", "year": "2004", "price": "4200",
             "url": "https://example.test/falcon-xt-ba"},
            "ford_falcon_xt_petrol_auto_sedan_ba",
            [{"body_type": "Ute"}, {"transmission": "Manual"},
             {"variant": "XR6 BA"}, {"variant": "XT BF", "year": "2006"}],
        ),
        (
            {"make": "Toyota", "model": "Camry", "variant": "Sportivo ACV40R",
             "body_type": "Sedan", "transmission": "Automatic", "fuel_type": "Petrol",
             "year": "2008", "price": "8000", "url": "https://example.test/camry-sportivo-acv40r"},
            "toyota_camry_sportivo_petrol_auto_sedan_acv40r",
            [{"variant": "Altise ACV40R"}, {"body_type": "Wagon"}, {"fuel_type": "Hybrid"}],
        ),
    ]
    for base_row, expected, changes in cases:
        assert assign_canonical_tag(base_row, require_price=True)[0:2] == (expected, "[OK]")
        for change in changes:
            assert assign_canonical_tag({**base_row, **change}, require_price=True)[0] != expected
