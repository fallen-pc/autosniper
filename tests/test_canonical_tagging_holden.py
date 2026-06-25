from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_assign_canonical_tag_accepts_holden_commodore_vf_evoke_and_sv6_sedan_and_wagon():
    _load_curve_year_band.cache_clear()
    evoke_row = {
        "make": "Holden",
        "model": "Commodore",
        "variant": "Evoke VF MY14 petrol automatic sedan",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2014",
        "price": "1200",
        "url": "https://www.example.com/2014-holden-commodore-evoke-vf-petrol-automatic-sedan",
    }
    sv6_row = {
        **evoke_row,
        "variant": "SV6 VF MY15 3.6 petrol automatic sedan",
        "year": "2015",
        "url": "https://www.example.com/2015-holden-commodore-sv6-vf-petrol-automatic-sedan",
    }
    wagon_row = {
        **sv6_row,
        "body_type": "Wagon",
        "variant": "SV6 VF petrol automatic sportwagon",
        "url": "https://www.example.com/2015-holden-commodore-sv6-vf-petrol-automatic-sportwagon",
    }
    ss_row = {
        **sv6_row,
        "variant": "SS V Redline VF petrol automatic sedan",
        "url": "https://www.example.com/2015-holden-commodore-ss-v-redline-vf-petrol-automatic-sedan",
    }

    assert assign_canonical_tag(evoke_row, require_price=True)[0:2] == (
        "holden_commodore_evoke_petrol_auto_sedan_vf",
        "[OK]",
    )
    assert assign_canonical_tag(sv6_row, require_price=True)[0:2] == (
        "holden_commodore_sv6_petrol_auto_sedan_vf",
        "[OK]",
    )
    assert assign_canonical_tag(wagon_row, require_price=True)[0:2] == (
        "holden_commodore_sv6_petrol_auto_wagon_vf",
        "[OK]",
    )
    assert assign_canonical_tag(ss_row, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_rejects_holden_commodore_vf_gas_only_wagon():
    _load_curve_year_band.cache_clear()
    gas_row = {
        "make": "Holden",
        "model": "Commodore",
        "variant": "Evoke VF gas only automatic sportwagon",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Gas Only",
        "year": "2014",
        "price": "1200",
        "url": "https://www.example.com/2014-holden-commodore-evoke-vf-gas-only-automatic-sportwagon",
    }

    assert assign_canonical_tag(gas_row, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_accepts_holden_commodore_ve_omega_and_sv6_sedan_and_wagon():
    _load_curve_year_band.cache_clear()
    omega_sedan = {
        "make": "Holden",
        "model": "Commodore",
        "variant": "Omega VE Auto MY09 petrol automatic sedan",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol - Unleaded ULP",
        "year": "2009",
        "price": "6000",
        "url": "https://www.example.com/2009-holden-commodore-omega-ve-auto-my09-sedan",
    }
    sv6_sedan = {
        **omega_sedan,
        "variant": "SV6 VE Auto MY09 petrol automatic sedan",
        "year": "2009",
        "url": "https://www.example.com/2009-holden-commodore-sv6-ve-auto-my09-sedan",
    }
    omega_wagon = {
        **omega_sedan,
        "body_type": "Wagon",
        "variant": "Omega VE Auto MY10 petrol automatic sportwagon",
        "url": "https://www.example.com/2009-holden-commodore-omega-ve-auto-my10-sportwagon",
    }
    sv6_wagon = {
        **omega_wagon,
        "variant": "SV6 VE Auto MY10 petrol automatic sportwagon",
        "url": "https://www.example.com/2010-holden-commodore-sv6-ve-auto-my10-sportwagon",
        "year": "2010",
    }

    assert assign_canonical_tag(omega_sedan, require_price=True)[0:2] == (
        "holden_commodore_omega_petrol_auto_sedan_ve",
        "[OK]",
    )
    assert assign_canonical_tag(sv6_sedan, require_price=True)[0:2] == (
        "holden_commodore_sv6_petrol_auto_sedan_ve",
        "[OK]",
    )
    assert assign_canonical_tag(omega_wagon, require_price=True)[0:2] == (
        "holden_commodore_omega_petrol_auto_wagon_ve",
        "[OK]",
    )
    assert assign_canonical_tag(sv6_wagon, require_price=True)[0:2] == (
        "holden_commodore_sv6_petrol_auto_wagon_ve",
        "[OK]",
    )


def test_assign_canonical_tag_keeps_holden_commodore_ve_series_ii_out_of_plain_ve_curve():
    _load_curve_year_band.cache_clear()
    series_ii = {
        "make": "Holden",
        "model": "Commodore",
        "variant": "Omega VE Series II Auto MY12",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol - Unleaded ULP",
        "year": "2012",
        "price": "6000",
        "url": "https://www.example.com/2012-holden-commodore-omega-ve-series-ii-auto-my12-wagon",
    }
    dual_fuel = {
        **series_ii,
        "variant": "Omega VE Auto MY09 dual fuel sedan",
        "body_type": "Sedan",
        "fuel_type": "Petrol Or LPG (dual)",
        "year": "2008",
        "url": "https://www.example.com/2008-holden-commodore-omega-ve-dual-fuel-sedan",
    }

    assert assign_canonical_tag(series_ii, require_price=True)[0] != (
        "holden_commodore_omega_petrol_auto_wagon_ve"
    )
    assert assign_canonical_tag(dual_fuel, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_accepts_holden_commodore_ve_series_ii_omega_wagon_only():
    _load_curve_year_band.cache_clear()
    omega_wagon = {
        "make": "Holden",
        "model": "Commodore",
        "variant": "Omega VE Series II Auto MY12 petrol automatic sportwagon",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol - Unleaded ULP",
        "year": "2012",
        "price": "6000",
        "url": "https://www.example.com/2012-holden-commodore-omega-ve-series-ii-auto-my12-wagon",
    }
    sv6_wagon = {
        **omega_wagon,
        "variant": "SV6 VE Series II Auto MY12 petrol automatic sportwagon",
        "url": "https://www.example.com/2012-holden-commodore-sv6-ve-series-ii-auto-my12-wagon",
    }
    gas_wagon = {
        **omega_wagon,
        "variant": "Omega VE Series II gas only automatic sportwagon",
        "fuel_type": "Gas Only",
        "url": "https://www.example.com/2012-holden-commodore-omega-ve-series-ii-gas-only-wagon",
    }

    assert assign_canonical_tag(omega_wagon, require_price=True)[0:2] == (
        "holden_commodore_omega_petrol_auto_wagon_ve-series-ii",
        "[OK]",
    )
    assert assign_canonical_tag(sv6_wagon, require_price=True)[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(gas_wagon, require_price=True)[0] == "UNCLASSIFIED"


def test_assign_canonical_tag_accepts_holden_commodore_ve_series_ii_omega_sedan_only():
    _load_curve_year_band.cache_clear()
    omega_sedan = {
        "make": "Holden",
        "model": "Commodore",
        "variant": "Omega VE Series II Auto MY12 petrol automatic sedan",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol - Unleaded ULP",
        "year": "2012",
        "price": "6000",
        "url": "https://www.example.com/2012-holden-commodore-omega-ve-series-ii-auto-my12-sedan",
    }
    wagon = {
        **omega_sedan,
        "body_type": "Wagon",
        "variant": "Omega VE Series II Auto MY12 petrol automatic sportwagon",
        "url": "https://www.example.com/2012-holden-commodore-omega-ve-series-ii-auto-my12-wagon",
    }

    assert assign_canonical_tag(omega_sedan, require_price=True)[0:2] == (
        "holden_commodore_omega_petrol_auto_sedan_ve-series-ii",
        "[OK]",
    )
    assert assign_canonical_tag(wagon, require_price=True)[0:2] == (
        "holden_commodore_omega_petrol_auto_wagon_ve-series-ii",
        "[OK]",
    )


def test_assign_canonical_tag_accepts_holden_captiva_cg_petrol_and_diesel_auto_suv():
    _load_curve_year_band.cache_clear()
    petrol_row = {
        "make": "Holden",
        "model": "Captiva",
        "variant": "7 SX 2WD CG Series II petrol automatic wagon",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol - Unleaded ULP",
        "year": "2012",
        "price": "5500",
        "url": "https://www.example.com/2012-holden-captiva-7-sx-cg-series-ii-auto-petrol-wagon",
    }
    diesel_row = {
        **petrol_row,
        "variant": "7 LX AWD CG Series II turbo diesel automatic wagon",
        "fuel_type": "Diesel",
        "url": "https://www.example.com/2012-holden-captiva-7-lx-cg-series-ii-diesel-auto-wagon",
    }
    manual_row = {
        **petrol_row,
        "variant": "5 CG manual petrol SUV",
        "transmission": "Manual",
        "url": "https://www.example.com/2011-holden-captiva-5-cg-manual-petrol-suv",
    }

    assert assign_canonical_tag(petrol_row, require_price=True)[0:2] == (
        "holden_captiva_petrol_auto_suv_cg",
        "[OK]",
    )
    assert assign_canonical_tag(diesel_row, require_price=True)[0:2] == (
        "holden_captiva_diesel_auto_suv_cg",
        "[OK]",
    )
    assert assign_canonical_tag(manual_row, require_price=True)[0] == "UNCLASSIFIED"
