import pandas as pd
import pytest

from ops import active_monitor
from shared import missed_opportunities


def _active_row(asset_id=137614):
    return {
        "source": "slattery",
        "url": f"https://slatteryauctions.com.au/assets/{asset_id}?auctionId=10301",
        "year": "2018", "make": "Toyota", "model": "RAV4",
        "odometer_reading": "52089", "vin": "JTMZDREV70D109973",
        "location": "Karratha WA", "general_condition": "Driver door scratched",
        "status": "Active", "price": "16200",
        "detail_completeness_status": "complete",
        "time_remaining_or_date_sold": (pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)).isoformat(),
    }


@pytest.mark.parametrize("changes", [
    {"status": ""}, {"status": "Unknown"}, {"status": "Closed"},
    {"detail_completeness_status": "incomplete"}, {"detail_completeness_status": ""},
    {"vin": ""}, {"location": ""}, {"general_condition": ""},
    {"time_remaining_or_date_sold": "2020-01-01T00:00:00Z"},
    {"time_remaining_or_date_sold": "unknown"},
])
def test_slattery_rediscovery_does_not_promote_unready_rows(monkeypatch, tmp_path, changes):
    good = _active_row()
    unsafe = {**_active_row(137615), **changes}
    matches = tmp_path / "matches.csv"
    links = tmp_path / "links.csv"
    pd.DataFrame([good, unsafe]).to_csv(matches, index=False)
    pd.DataFrame([{"url": good["url"]}, {"url": unsafe["url"]}]).to_csv(links, index=False)
    monkeypatch.setattr(active_monitor, "_external_auction_matches_path", lambda: matches)
    monkeypatch.setattr(active_monitor, "_external_auction_links_path", lambda: links)
    result = active_monitor._load_external_auction_active_rows()
    assert result["url"].tolist() == [good["url"]]


def test_slattery_hostname_is_guarded_even_when_source_is_missing(monkeypatch, tmp_path):
    matches = tmp_path / "matches.csv"
    pd.DataFrame([{**_active_row(), "source": "", "status": "Unknown"}]).to_csv(matches, index=False)
    monkeypatch.setattr(active_monitor, "_external_auction_matches_path", lambda: matches)
    assert active_monitor._load_external_auction_active_rows().empty


def test_slattery_closed_last_bid_is_not_a_sale(tmp_path):
    path = tmp_path / "matches.csv"
    rows = [
        {**_active_row(1), "status": "Closed", "date_sold": "2026-09-09", "final_sale_price": "16200"},
        {**_active_row(2), "status": "Sold", "date_sold": "2026-09-09", "final_sale_price": ""},
        {**_active_row(3), "status": "Sold", "date_sold": "", "final_sale_price": "16200"},
        {**_active_row(4), "status": "Sold", "date_sold": "2026-09-09", "final_sale_price": "17000"},
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    result = missed_opportunities.load_external_auction_sold_rows(path)
    assert result["url"].tolist() == [rows[3]["url"]]
    assert result.iloc[0]["price_numeric"] == 17000
