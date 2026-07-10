import pandas as pd

from scripts.scrape_external_auction_sources import (
    build_source_list_urls,
    extract_label_values,
    filter_curve_supported,
    parse_listing_text,
    parse_title_parts,
    split_detail_lines,
    tag_discovered_links,
    tag_with_curve_support,
    BrowserListing,
)


def test_parse_pickles_detail_text_extracts_grays_like_fields():
    text = """
    STOCK 62322426
    2024 Hyundai Tucson
    NX4.V2 MY24 Elite N Line Wagon 5dr. Auto 6sp 2WD 2.0i
    Odometer (Showing on)
    46,824 km
    Service History
    Partial Service History
    Owners Manual
    Available
    Transmission
    6 Spd Automatic
    Engine Capacity
    2 Ltr
    Fuel
    Multi-Point Injection Petrol - Unleaded ULP
    Cylinders
    4
    Registration
    No Registration
    No. of Seats
    5
    VIN
    KMHJC81DMRU338393
    Sunshine North, VIC
    """
    row = parse_listing_text(
        "pickles",
        "https://www.pickles.com.au/used/details/cars/2024-hyundai-tucson/62322426",
        "2024 Hyundai Tucson, 62322426 - Pickles AU",
        text,
    )

    assert row["year"] == "2024"
    assert row["make"] == "Hyundai"
    assert row["model"] == "Tucson"
    assert row["variant"].startswith("NX4 V2 MY24 Elite")
    assert row["body_type"] == "Wagon"
    assert row["transmission"] == "Automatic"
    assert row["fuel_type"] == "Petrol"
    assert row["odometer_reading"] == "46824"
    assert row["vin"] == "KMHJC81DMRU338393"
    assert row["no_of_seats"] == "5"


def test_parse_pickles_condition_details_into_repair_fragments():
    text = """
    STOCK 62278257
    2019 Toyota Hilux
    GUN126R SR Cab Chassis Single Cab 2dr Spts Auto 6sp 4x4 1235kg 2.8DT
    Condition Details (12)
    Tyres
    1. Tyre (Spare)
    Missing
    Requires Quote
    2. Wheel (Spare)
    Missing
    Requires Quote
    3. Vehicle Body
    Minor Paint Chips, Small Dents & Scratches Visible
    Comment Only
    5. Door (Driver)
    Dents ,Scrapes ,Scratches
    Comment Only
    8. Chassis/Undercarriage
    Bubbling/Delamination Corrosion Evident
    Requires Quote
    10. Windscreen (Front)
    Minor Pitting Visible
    Comment Only
    11. Mechanical
    Mechanical Issue - Requires Attention
    Requires Quote
    12. Battery Std Light Commercial
    Flat
    RR&P* Level 1
    Damage and Description Disclaimer
    Location
    """
    row = parse_listing_text(
        "pickles",
        "https://www.pickles.com.au/used/details/cars/2019-toyota-hilux/62278257",
        "2019 Toyota Hilux, 62278257 - Pickles AU",
        text,
    )

    condition = row["general_condition"]
    assert "Damage and Description Disclaimer" not in condition
    assert "Requires Quote" not in condition
    assert "Comment Only" not in condition
    assert "Tyre (Spare) missing." in condition
    assert "Wheel (Spare) missing." in condition
    assert "Vehicle Body minor paint chips, small dents & scratches visible." in condition
    assert "Door (Driver) dents, scrapes, scratches." in condition
    assert "Chassis/Undercarriage bubbling/delamination corrosion evident." in condition
    assert "Windscreen (Front) minor pitting visible." in condition
    assert "Mechanical mechanical issue - requires attention." in condition
    assert "Battery Std Light Commercial flat." in condition


def test_parse_manheim_detail_text_extracts_identity_and_static_fields():
    text = """
    2023 Toyota Corolla Ascent Sport 4D Sedan
    Build Year:
    2023
    Make:
    Toyota
    Body Type:
    4D Sedan
    Model:
    Corolla
    Variant:
    Ascent Sport
    Seats:
    5
    Odometer:
    73,905 KM Showing
    Transmission:
    CVT
    Engine: 4 Cyl 1.8 L
    Fuel Type:
    Hybrid
    VIN: JTDBC3FE00J021655
    Reg Expiry:
    UnReg
    Item Location: Moorebank, Sydney, New South Wales
    """
    row = parse_listing_text(
        "manheim",
        "https://www.manheim.com.au/passenger-vehicles/000000000007401878/2023-toyota-corolla-ascent-sport-4d-sedan",
        "2023 Toyota Corolla Ascent Sport 4D Sedan - Used Car for Sale - Manheim",
        text,
    )

    assert row["year"] == "2023"
    assert row["make"] == "Toyota"
    assert row["model"] == "Corolla"
    assert row["variant"] == "Ascent Sport"
    assert row["body_type"] == "Sedan"
    assert row["transmission"] == "CVT"
    assert row["fuel_type"] == "Hybrid"
    assert row["odometer_reading"] == "73905"
    assert row["vin"] == "JTDBC3FE00J021655"


def test_parse_slattery_asset_text_extracts_condition_fragments():
    text = """
    Asset Name
    2019 Hyundai Santa Fe Highlander 4WD Wagon (Diesel) (Auto)
    Sports Automatic
    Transmission
    Diesel
    Fuel Type
    Four Wheel Drive
    Drive Type
    147,621 KMs Showing
    Odometer
    Year Of Manufacture
    2019
    Body Type
    SUV
    Registration Number
    NO PLATES
    Owners Manual
    Yes
    No of Seats
    7
    Keys
    Yes
    Asset Condition
    Driveable
    Body Condition
    Good
    Damage
    Scratches and dents visible around vehicle
    """
    row = parse_listing_text(
        "slattery",
        "https://slatteryauctions.com.au/assets/122216?auctionId=6635",
        "Slattery Auctions: Auto & Car Auctions Australia",
        text,
    )

    assert row["year"] == "2019"
    assert row["make"] == "Hyundai"
    assert row["model"] == "Santa Fe"
    assert row["body_type"] == "SUV"
    assert row["fuel_type"] == "Diesel"
    assert row["odometer_reading"] == "147621"
    assert row["key"] == "Yes"
    assert "Damage: Scratches and dents" in row["general_condition"]


def test_extract_label_values_accepts_colon_and_next_line_forms():
    lines = split_detail_lines(
        """
        VIN: ABC123
        Odometer:
        12,345 KM Showing
        Fuel Type
        Hybrid
        """
    )

    values = extract_label_values(lines)

    assert values["vin"] == "ABC123"
    assert values["odometer_reading"] == "12,345 KM Showing"
    assert values["fuel_type"] == "Hybrid"


def test_filter_curve_supported_keeps_saved_curve_match():
    rows = pd.DataFrame(
        [
            {
                "source": "manheim",
                "url": "https://example.test/2013-toyota-camry-altise-asv50r",
                "year": "2013",
                "make": "Toyota",
                "model": "Camry",
                "variant": "Altise ASV50R Sedan",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "odometer_reading": "100000",
            },
            {
                "source": "manheim",
                "url": "https://example.test/2024-bmw-x2",
                "year": "2024",
                "make": "BMW",
                "model": "X2",
                "variant": "M Sport",
                "body_type": "Wagon",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "odometer_reading": "10000",
            },
        ]
    )

    matched = filter_curve_supported(rows)

    assert len(matched) == 1
    assert matched.iloc[0]["model"] == "Camry"
    assert matched.iloc[0]["curve_tag"]


def test_tag_with_curve_support_keeps_rejection_reason_for_all_rows():
    rows = pd.DataFrame(
        [
            {
                "source": "slattery",
                "url": "https://example.test/2024-bmw-x2",
                "year": "2024",
                "make": "BMW",
                "model": "X2",
                "variant": "M Sport",
                "body_type": "Wagon",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "odometer_reading": "10000",
            }
        ]
    )

    tagged = tag_with_curve_support(rows)

    assert tagged.iloc[0]["canonical_tag"] == "UNCLASSIFIED"
    assert tagged.iloc[0]["canonical_reason"]


def test_parse_title_parts_handles_common_make_model_title():
    parts = parse_title_parts("2025 Toyota Corolla ZWE219R Ascent Sport 4D Sedan")

    assert parts["year"] == "2025"
    assert parts["make"] == "Toyota"
    assert parts["model"] == "Corolla"
    assert parts["variant"].startswith("ZWE219R Ascent Sport")


def test_parse_title_parts_handles_pickles_stock_title_with_body_heading():
    row = parse_listing_text(
        "pickles",
        "https://www.pickles.com.au/used/details/cars/2019-toyota-hilux/62341652",
        "2019 Toyota Hilux, 62341652 - Pickles AU",
        """
        STOCK 62341652
        2019 Toyota Hilux
        GUN126R SR Utility Double Cab 4dr Spts Auto 6sp 4x4 955kg 2.8DT
        Odometer (Showing on)
        218,226 km
        Transmission
        6 Spd Sports Automatic
        Fuel
        Direct Injection Diesel
        """,
    )

    assert row["variant"].startswith("GUN126R SR Utility")
    assert row["body_type"] == "Dual Cab"
    assert row["transmission"] == "Automatic"
    assert row["fuel_type"] == "Diesel"


def test_build_source_list_urls_expands_pickles_pages():
    urls = build_source_list_urls("pickles", 3)

    assert len(urls) == 3
    assert "page=1" in urls[0]
    assert "page=3" in urls[2]


def test_tag_discovered_links_prefers_saved_curve_titles():
    links = [
        BrowserListing(
            source="manheim",
            url="https://example.test/2013-toyota-camry-altise-asv50r",
            title_hint="2013 Toyota Camry Altise ASV50R Sedan Automatic Petrol",
        ),
        BrowserListing(
            source="manheim",
            url="https://example.test/2024-bmw-x2",
            title_hint="2024 BMW X2 M Sport Wagon Automatic Petrol",
        ),
        BrowserListing(
            source="slattery",
            url="https://example.test/unknown-title",
            title_hint="",
        ),
    ]

    tagged = tag_discovered_links(links)

    selected = dict(zip(tagged["url"], tagged["selected_for_detail"]))
    assert selected["https://example.test/2013-toyota-camry-altise-asv50r"] == "1"
    assert selected["https://example.test/2024-bmw-x2"] == "0"
    assert selected["https://example.test/unknown-title"] == "1"


def test_tag_discovered_links_keeps_ambiguous_supported_title_for_detail():
    links = [
        BrowserListing(
            source="manheim",
            url="https://example.test/2017-toyota-camry-asv50r-altise",
            title_hint="2017 Toyota Camry ASV50R Altise 4D Sedan",
        )
    ]

    tagged = tag_discovered_links(links)

    assert tagged.iloc[0]["canonical_reason"] == "[AMBIG_FUEL]"
    assert tagged.iloc[0]["selected_for_detail"] == "1"
