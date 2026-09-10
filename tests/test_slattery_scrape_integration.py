import asyncio
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import scrape_external_auction_sources as scraper


class _Response:
    def __init__(self, text, *, status=200, url="https://slatteryauctions.com.au/assets/137614?auctionId=10301"):
        self.payload, self.status, self.url = text, status, url
        self.disposed = False

    async def text(self):
        return self.payload

    async def dispose(self):
        self.disposed = True


class _RequestContext:
    def __init__(self, response):
        self.response = response
        self.request = self
        self.urls = []

    async def get(self, url, **kwargs):
        self.urls.append(url)
        return self.response


def _scrape(response):
    context = _RequestContext(response)
    row = asyncio.run(scraper.scrape_detail(
        context,
        scraper.BrowserListing(
            "slattery", "https://slatteryauctions.com.au/assets/137614?auctionId=10301&utm_source=grays",
            discovery_urls=("https://www.grays.com/search?q=toyota",),
        ),
        detail_timeout_ms=5000, detail_wait_ms=0,
    ))
    assert response.disposed
    return row, context


def test_public_hydration_details_survive_scrape_and_output(monkeypatch, tmp_path):
    asset = json.loads((Path(__file__).parent / "fixtures/slattery_asset.json").read_text(encoding="utf-8"))
    payload = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"asset": asset}) + "</script>"
    row, context = _scrape(_Response(payload))
    assert context.urls == ["https://slatteryauctions.com.au/assets/137614?auctionId=10301"]
    assert row["url"] == context.urls[0]
    assert row["requested_url"].endswith("utm_source=grays")
    assert row["vin"] == asset["detailAttributes"]["vin"]
    assert row["odometer_reading"] == "52089"
    assert "Karratha" in row["location"]
    assert "Scratched" in row["general_condition"]
    assert row["status"] == "Closed"
    assert row["final_sale_price"] == row["date_sold"] == ""
    assert row["detail_completeness_status"] == "complete"
    assert row["scrape_status"] == "parsed_http_200"
    # Extra external evidence fields must reach the saved curve-match path.
    monkeypatch.setattr(scraper, "tag_with_curve_support", lambda df: df)
    monkeypatch.setattr(scraper, "filter_curve_supported", lambda df: df)
    _, _, matched = scraper.write_outputs(pd.DataFrame([row]), pd.DataFrame(), tmp_path)
    saved = pd.read_csv(matched).iloc[0]
    for field in ("requested_url", "discovery_urls", "detail_completeness_status", "auction_fee_schedule", "auction_fee_status"):
        assert str(saved[field]) == str(row[field])


@pytest.mark.parametrize("response, expected", [
    (_Response("<html>Loading</html>"), "error:slattery_asset_identity_unverified"),
    (_Response("<html>Access denied</html>", status=403), "error:http_403"),
    (_Response("<html>Unavailable</html>", url="https://example.com/unavailable"), "error:unexpected_slattery_redirect"),
])
def test_transport_or_identity_failure_cannot_be_a_live_candidate(response, expected):
    row, _ = _scrape(response)
    assert row["scrape_status"] == expected
    assert row["status"] == "Unknown"
    assert row["detail_completeness_status"] == "incomplete"
    assert row["price"] == row["vin"] == ""
