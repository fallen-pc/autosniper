from __future__ import annotations

import pandas as pd

import scripts.extract_links as extract_links


def test_extract_links_merges_active_queue_instead_of_replacing(monkeypatch, tmp_path) -> None:
    all_path = tmp_path / "all_vehicle_links.csv"
    active_path = tmp_path / "active_vehicle_links.csv"
    sold_path = tmp_path / "sold_cars.csv"
    referred_path = tmp_path / "referred_cars.csv"
    summary_path = tmp_path / "link_scrape_summary.json"

    existing_url = "https://www.grays.com/lot/0001-existing/motor-vehicles-motor-cycles/existing-car"
    new_url = "https://www.grays.com/lot/0002-new/motor-vehicles-motor-cycles/new-car"
    sold_url = "https://www.grays.com/lot/0003-sold/motor-vehicles-motor-cycles/sold-car"

    pd.DataFrame([{"url": existing_url}]).to_csv(active_path, index=False)
    pd.DataFrame([{"url": sold_url}]).to_csv(sold_path, index=False)
    pd.DataFrame(columns=["url"]).to_csv(referred_path, index=False)

    monkeypatch.setattr(extract_links, "OUTPUT_FILE", all_path)
    monkeypatch.setattr(extract_links, "ACTIVE_OUTPUT_FILE", active_path)
    monkeypatch.setattr(extract_links, "SOLD_FILE", sold_path)
    monkeypatch.setattr(extract_links, "REFERRED_FILE", referred_path)
    monkeypatch.setattr(extract_links, "SUMMARY_FILE", summary_path)
    monkeypatch.setattr(extract_links, "fetch_page", lambda session, url, force_proxy=False: (new_url, True))

    extract_links.extract_all_vehicle_links(max_pages=1)

    active_urls = set(pd.read_csv(active_path)["url"].tolist())
    assert active_urls == {existing_url.lower(), new_url.lower()}
