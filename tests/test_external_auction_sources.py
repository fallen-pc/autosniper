import asyncio

import pandas as pd

from scripts.scrape_external_auction_sources import (
    build_source_list_urls,
    discover_source_links,
    extract_label_values,
    filter_curve_supported,
    parse_listing_text,
    parse_title_parts,
    scrape_detail,
    split_detail_lines,
    _scrape_detail_batches,
    _discover_source_links_with_browser_recycling,
    tag_discovered_links,
    tag_with_curve_support,
    BrowserListing,
)


class _FakeResponse:
    def __init__(self, status: int = 200):
        self.status = status

    async def text(self):
        return ""


class _FakeListPage:
    def __init__(self, *, anchors=None, status: int = 200):
        self.anchors = anchors or []
        self.status = status

    async def goto(self, *_args, **_kwargs):
        return _FakeResponse(self.status)

    async def wait_for_timeout(self, *_args, **_kwargs):
        return None

    async def evaluate(self, script):
        return 100 if script == "document.body.scrollHeight" else None

    async def eval_on_selector_all(self, *_args, **_kwargs):
        return self.anchors

    async def content(self):
        return ""

    async def close(self):
        return None


class _FakeListContext:
    def __init__(self, pages):
        self.pages = iter(pages)

    async def new_page(self):
        return next(self.pages)


class _FakeDetailLocator:
    def __init__(self, text: str = ""):
        self.text = text
        self.first = self

    async def count(self):
        return 0

    async def inner_text(self, **_kwargs):
        return self.text


class _FakeUnavailableDetailPage:
    url = "https://www.pickles.com.au/services/item-not-available?errorcode=20"

    async def goto(self, *_args, **_kwargs):
        return _FakeResponse(200)

    async def wait_for_timeout(self, *_args, **_kwargs):
        return None

    async def title(self):
        return "Page not found - Pickles"

    def locator(self, selector):
        return _FakeDetailLocator("Page not found" if selector == "body" else "")

    async def content(self):
        return "<html><body>Page not found</body></html>"

    async def close(self):
        return None


class _FakeRecycledContext:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class _FakeRecycledBrowser:
    def __init__(self):
        self.context = _FakeRecycledContext()
        self.closed = False

    async def new_context(self, **_kwargs):
        return self.context

    async def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self):
        self.browsers = []

    async def launch(self, **_kwargs):
        browser = _FakeRecycledBrowser()
        self.browsers.append(browser)
        return browser


class _FakePlaywright:
    def __init__(self):
        self.chromium = _FakeChromium()


def test_detail_batches_recycle_and_close_browsers(monkeypatch):
    playwright = _FakePlaywright()
    listings = [
        BrowserListing(source="pickles", url=f"https://example.test/{index}", title_hint=str(index))
        for index in range(85)
    ]
    active = 0
    max_active = 0

    async def fake_scrape_detail(_context, listing, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return {"source": listing.source, "url": listing.url, "title": listing.title_hint}

    monkeypatch.setattr("scripts.scrape_external_auction_sources.scrape_detail", fake_scrape_detail)

    rows = asyncio.run(
        _scrape_detail_batches(
            playwright,
            listings,
            headless=True,
            detail_timeout_ms=5_000,
            detail_wait_ms=0,
            browser_recycle_size=40,
            detail_batch_size=2,
        )
    )

    assert len(rows) == 85
    assert max_active == 2
    assert len(playwright.chromium.browsers) == 3
    assert all(browser.closed for browser in playwright.chromium.browsers)
    assert all(browser.context.closed for browser in playwright.chromium.browsers)


def test_discovery_recycles_and_closes_browsers(monkeypatch):
    playwright = _FakePlaywright()
    list_urls = [f"https://example.test/list/{index}" for index in range(25)]

    async def fake_discover_page(_context, url):
        index = url.rsplit("/", 1)[-1]
        detail_url = f"https://www.pickles.com.au/used/details/cars/2020-toyota-camry/{index}"
        return 200, [[detail_url, f"2020 Toyota Camry {index}"]], ""

    monkeypatch.setattr("scripts.scrape_external_auction_sources._discover_list_page", fake_discover_page)

    result = asyncio.run(
        _discover_source_links_with_browser_recycling(
            playwright,
            "pickles",
            list_urls,
            headless=True,
            browser_recycle_pages=10,
        )
    )

    assert result.pages_visited == 25
    assert len(result.listings) == 25
    assert len(playwright.chromium.browsers) == 3
    assert all(browser.closed for browser in playwright.chromium.browsers)
    assert all(browser.context.closed for browser in playwright.chromium.browsers)
def test_discovery_stops_after_pagination_is_exhausted():
    detail_url = "https://www.pickles.com.au/used/details/cars/2019-toyota-hilux/62341652"
    context = _FakeListContext(
        [
            _FakeListPage(anchors=[[detail_url, "2019 Toyota Hilux"]]),
            _FakeListPage(),
            _FakeListPage(),
        ]
    )

    result = asyncio.run(
        discover_source_links(
            context,
            "pickles",
            build_source_list_urls("pickles", 10),
            max_details=0,
        )
    )

    assert len(result.listings) == 1
    assert result.pages_visited == 3
    assert result.pagination_exhausted is True
    assert result.page_cap_reached is False


def test_unavailable_pickles_redirect_keeps_discovered_url_for_reconciliation():
    requested_url = "https://www.pickles.com.au/used/details/cars/1970-ford-falcon/62227656"
    context = _FakeListContext([_FakeUnavailableDetailPage()])

    row = asyncio.run(
        scrape_detail(
            context,
            BrowserListing(source="pickles", url=requested_url, title_hint="1970 Ford Falcon"),
            detail_timeout_ms=5_000,
            detail_wait_ms=0,
        )
    )

    assert row["url"] == requested_url
    assert row["scrape_status"] == "unavailable_redirect"


def test_manheim_block_is_counted_across_both_locations():
    context = _FakeListContext([_FakeListPage(status=403) for _ in range(4)])

    result = asyncio.run(
        discover_source_links(
            context,
            "manheim",
            build_source_list_urls("manheim", 10),
            max_details=0,
        )
    )

    assert result.listings == []
    assert result.pages_visited == 4
    assert result.blocked_pages == 4
    assert result.pagination_exhausted is True
    assert result.page_cap_reached is False


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


def test_parse_pickles_condition_details_stops_before_item_info_metadata():
    text = """
    STOCK 62363135
    2020 Ford Ranger
    PX MkIII MY21.25 Wildtrak Pick-up Double Cab 4dr Spts Auto 10sp 4x4 954kg 2.0DTT
    Condition Details
    Item Info (Print)
    Keys
    No
    Spare Keys
    Grey
    Compliance Date
    12/2020
    Build Date
    11/2020
    Odometer (Showing on)
    117,116 km
    Transmission
    10 Spd Sports Automatic
    Registration
    No Registration
    VIN
    MPBUMFF60LX313235
    """

    row = parse_listing_text(
        "pickles",
        "https://www.pickles.com.au/used/details/cars/2020-ford-ranger/62363135",
        "2020 Ford Ranger, 62363135 - Pickles AU",
        text,
    )

    assert row["general_condition"] == ""


def test_parse_pickles_metadata_sequence_preserves_explicit_transport_risk():
    text = """
    STOCK 62335694
    2023 Toyota Hilux
    Condition Details
    2023 Toyota Hilux GUN126R SR Cab Chassis Dual Cab
    Keys
    Spare Keys
    White
    Compliance Date
    03/2023
    Build Date
    02/2023
    Odometer (Showing on)
    54,642 km
    Service History
    No Service History
    Owners Manual
    None
    Transmission
    6 Spd Sports Automatic
    Registration
    No Registration
    VIN
    MR0KA3CD601288270
    ******this asset is a non runner, tilt tray required for collection *******
    """

    row = parse_listing_text(
        "pickles",
        "https://www.pickles.com.au/used/details/cars/2023-toyota-hilux/62335694",
        "2023 Toyota Hilux, 62335694 - Pickles AU",
        text,
    )

    assert row["general_condition"] == "this asset is a non runner, tilt tray required for collection"


def test_parse_pickles_late_metadata_sequence_fails_closed_before_legal_disclaimer():
    filler = "\n".join(f"Observation {index}\nValue {index}" for index in range(16))
    text = f"""
    STOCK 62288698
    2024 Toyota Hilux
    Condition Details (6)
    {filler}
    Keys
    Spare Keys
    White
    Compliance Date
    02/2024
    Build Date
    01/2024
    Odometer (Showing on)
    102,133 km
    Registration
    Last registered as 553KB2
    VIN
    MR0KA3CD206807270
    Please note - This Vehicle will need to be transported on Suitable Transport
    Moranbah, QLD
    Damage and Description Disclaimer
    Please Note: This description is generic legal boilerplate.
    """

    row = parse_listing_text(
        "pickles",
        "https://www.pickles.com.au/used/details/cars/2024-toyota-hilux/62288698",
        "2024 Toyota Hilux, 62288698 - Pickles AU",
        text,
    )

    assert row["general_condition"] == "Please note - This Vehicle will need to be transported on Suitable Transport"
    assert "legal boilerplate" not in row["general_condition"]


def test_parse_pickles_condition_stops_before_prefixed_terminal_disclaimer():
    text = """
    STOCK 62330787
    2021 Toyota Hilux
    Condition Details (4)
    Attachments (1)
    Vehicle Body
    Minor Stone Chips, Scratches & Dents
    Sill Panel (Passenger)
    Corrosion Evident, Scratches
    No longer available
    Sorry this item is no longer available. Find similar items. view similar items.
    ENDED
    Please Note: This description indicates the motor vehicle has a body appraisal based purely on an external walk around.
    Without limiting the generality of this disclaimer, there may be other damage.
    """

    row = parse_listing_text(
        "pickles",
        "https://www.pickles.com.au/used/details/cars/2021-toyota-hilux/62330787",
        "2021 Toyota Hilux, 62330787 - Pickles AU",
        text,
    )

    assert row["general_condition"] == (
        "Vehicle Body minor stone chips, scratches & dents.\n"
        "Sill Panel (Passenger) corrosion evident, scratches."
    )
    assert "no longer available" not in row["general_condition"].lower()
    assert "attachments" not in row["general_condition"].lower()
    assert "body appraisal" not in row["general_condition"].lower()


def test_parse_pickles_embedded_sold_fields_into_grays_like_columns():
    text = r"""
    STOCK 62146160
    2018 Toyota Hilux
    GUN126R SR Cab Chassis Double Cab 4dr Spts Auto 6sp 4x4 1045kg 2.8DT
    Odometer (Showing on)
    155,100 km
    {\"stockNumber\":\"62146160\",\"dateSold\":\"2026-06-17T07:00:00.000Z\",\"currentBid\":27100}
    """

    row = parse_listing_text(
        "pickles",
        "https://www.pickles.com.au/used/details/cars/2018-toyota-hilux/62146160",
        "2018 Toyota Hilux, 62146160 - Pickles AU",
        text,
    )

    assert row["status"] == "Sold"
    assert row["date_sold"] == "2026-06-17T07:00:00.000Z"
    assert row["time_remaining_or_date_sold"] == "2026-06-17T07:00:00.000Z"
    assert row["price"] == "27100"


def test_parse_pickles_sold_unregistered_boilerplate_does_not_mark_sold():
    text = r"""
    STOCK 62278257
    2019 Toyota Hilux
    GUN126R SR Cab Chassis Double Cab 4dr Spts Auto 6sp 4x4 1045kg 2.8DT
    Odometer (Showing on)
    100,100 km
    {\"stockNumber\":\"62278257\",\"importantBuyerInfo\":[\"THIS VEHICLE IS SOLD UNREGISTERED AUSTRALIA WIDE\"],\"currentBid\":12000}
    """

    row = parse_listing_text(
        "pickles",
        "https://www.pickles.com.au/used/details/cars/2019-toyota-hilux/62278257",
        "2019 Toyota Hilux, 62278257 - Pickles AU",
        text,
    )

    assert row["status"] == ""
    assert row["date_sold"] == ""
    assert row["price"] == ""


def test_parse_pickles_no_longer_available_marks_terminal_without_fabricating_price():
    text = r"""
    STOCK 62339379
    2017 Toyota Hilux
    GUN126R SR Cab Chassis Double Cab 4dr Spts Auto 6sp 4x4 1045kg 2.8DT
    No longer available
    Sorry this item is no longer available.
    SOLD
    {\"stockNumber\":\"62339379\",\"lotEndTime\":\"2026-07-12T10:00:00.000Z\"}
    """

    row = parse_listing_text(
        "pickles",
        "https://www.pickles.com.au/used/details/cars/2017-toyota-hilux/62339379",
        "2017 Toyota Hilux, 62339379 - Pickles AU",
        text,
    )

    assert row["status"] == "Sold"
    assert row["time_remaining_or_date_sold"] == "2026-07-12T10:00:00.000Z"
    assert row["date_sold"] == ""
    assert row["price"] == ""


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


def test_parse_slattery_embedded_payload_extracts_asset_scoped_live_bid_fields():
    payload = r'''
    {\"id\":138753,\"closesAt\":\"2026-08-10T06:34:18Z\",\"startingBidAmount\":18000,\"bidCount\":2,
    \"auctionAssetBids\":[
      {\"assetId\":138753,\"bidAmount\":18000},
      {\"assetId\":138753,\"bidAmount\":18100},
      {\"assetId\":999999,\"bidAmount\":99900}
    ]}
    '''

    row = parse_listing_text(
        "slattery",
        "https://slatteryauctions.com.au/assets/138753?auctionId=10529",
        "2020 Toyota Corolla Ascent Sport",
        payload,
    )

    assert row["price"] == "18100"
    assert row["bids"] == "2"
    assert row["time_remaining_or_date_sold"] == "2026-08-10T06:34:18Z"


def test_parse_slattery_embedded_payload_uses_starting_bid_when_no_bids_exist():
    payload = r'''
    {\"id\":138753,\"closesAt\":\"2026-08-10T06:34:18Z\",\"startingBidAmount\":18000,
    \"bidCount\":0,\"auctionAssetBids\":[]}
    '''

    row = parse_listing_text(
        "slattery",
        "https://slatteryauctions.com.au/assets/138753?auctionId=10529",
        "2020 Toyota Corolla Ascent Sport",
        payload,
    )

    assert row["price"] == "18000"
    assert row["bids"] == "0"


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


def test_build_source_list_urls_interleaves_manheim_locations_by_page():
    urls = build_source_list_urls("manheim", 2)

    assert len(urls) == 4
    assert "sydney" in urls[0] and "page=1" in urls[0]
    assert "melbourne" in urls[1] and "page=1" in urls[1]
    assert "sydney" in urls[2] and "page=2" in urls[2]
    assert "melbourne" in urls[3] and "page=2" in urls[3]


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
