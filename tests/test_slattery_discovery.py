import asyncio
import json
from urllib.parse import urlencode

import pandas as pd
import pytest

from scripts import scrape_external_auction_sources as scraper


NUMERIC = "https://slatteryauctions.com.au/assets/137614?auctionId=10301"
ALPHA = "https://slatteryauctions.com.au/assets/02iOa00000EHP8PIAX?auctionId=a0lOa00000PfsvhIAB"
OTHER = "https://slatteryauctions.com.au/assets/139070?auctionId=10727"
NATIVE_GRAYS = "https://www.grays.com/lot/0001-23502122/motor-vehicles-motor-cycles/2018-toyota-rav4"


def api_page(page, assets, *, total=2, total_pages=2, has_next=None):
    return 200, [], json.dumps({
        "ok": True, "status": 200, "data": assets,
        "metadata": {
            "currentPage": page, "totalPages": total_pages, "pageSize": 1,
            "totalCount": total, "hasPrevious": page > 1,
            "hasNext": page < total_pages if has_next is None else has_next,
        },
    })


def asset(asset_id=137614, auction_id=10301):
    return {"id": asset_id, "auctionId": auction_id, "name": "2018 Toyota RAV4 GX Petrol"}


def alias_html(*, wrong_auction=False):
    return "<script>" + json.dumps({
        "c": ["", "assets", ALPHA.rsplit("/", 1)[1]],
        "asset": {**asset(137614, 10302 if wrong_auction else 10301), "sfid": "02iOa00000EHP8PIAX"},
    }) + "</script>"


def referral():
    return "/redirection/interimPage?" + urlencode({
        "url": ALPHA.replace("https://", "https://www.") + "&utm_source=grays",
        "title": "2018 Toyota RAV4 GX Petrol",
    })


def grays_page(anchors, *, total, more=False):
    # Captured 11 September 2026: the SSR footer reports page-local shown rows,
    # total results, and a Load More button only while another page exists.
    footer = f'<footer aria-label="Pagination"><p>Showing <!-- -->{len(anchors)}<!-- --> of <!-- -->{total}<!-- --> results</p>'
    return 200, anchors, footer + ("<button>Load More</button>" if more else "") + "</footer>"


def run_discovery(responses, *, pages=2, seeds=(), max_details=0):
    requested = []

    async def load(urls):
        requested.extend(urls)
        return [responses[url] for url in urls]

    result = asyncio.run(scraper.discover_source_links(
        None, "slattery", scraper.build_source_list_urls("slattery", pages),
        max_details=max_details, page_batch_loader=load, seed_listings=seeds,
    ))
    return result, requested


def base_responses(pages=2):
    urls = scraper.build_source_list_urls("slattery", pages)
    return {
        urls[0]: api_page(1, [asset()]),
        urls[1]: api_page(2, [asset(139070, 10727)]),
        urls[pages]: grays_page([[NATIVE_GRAYS, "Grays vehicle"]], total=2, more=True),
        urls[pages + 1]: grays_page([[referral(), "View on Slattery"]], total=2),
        ALPHA: (200, [], alias_html()),
    }


def test_traverses_actual_metadata_and_reconciles_referral_and_seed_before_selection():
    responses = base_responses()
    seeds = [scraper.BrowserListing("slattery", ALPHA + "&utm_source=grays")]
    result, requested = run_discovery(responses, seeds=seeds)

    assert [listing.url for listing in result.listings] == [NUMERIC, OTHER]
    assert [listing.url for listing in result.seed_listings] == [NUMERIC]
    assert requested.count(ALPHA) == 1
    assert result.pages_visited == result.pages_planned == 4
    assert result.pagination_exhausted is True
    assert result.page_cap_reached is False
    assert result.incomplete_reasons == ()
    assert NATIVE_GRAYS not in [listing.url for listing in result.listings]
    assert len(result.listings[0].discovery_urls) == 2
    assert ALPHA in result.listings[0].url_aliases
    assert any("interimPage" in alias for alias in result.listings[0].url_aliases)


def test_stops_after_verified_final_pages_without_requesting_configured_tail():
    urls = scraper.build_source_list_urls("slattery", 5)
    responses = {
        urls[0]: api_page(1, [asset()], total=1, total_pages=1),
        urls[5]: grays_page([[NATIVE_GRAYS, "Grays vehicle"]], total=1),
    }
    result, requested = run_discovery(responses, pages=5)
    assert result.pagination_exhausted is True
    assert requested == [urls[0], urls[5]]
    assert result.pages_planned == 2


def test_current_discovery_merges_saved_provenance_without_rediscovering_seed_only_urls():
    historical_discovery = "https://www.grays.com/search?q=toyota&tab=items"
    historical_alias = "https://www.slatteryauctions.com.au/assets/137614?auctionId=10301&utm_source=grays"
    seed_only_url = "https://slatteryauctions.com.au/assets/999999?auctionId=10301"
    seed_only_discovery = "https://slatteryauctions.com.au/categories/motor-vehicles"
    result, requested = run_discovery(base_responses(), seeds=[
        scraper.BrowserListing("slattery", ALPHA, "Saved RAV4", (historical_discovery,), (historical_alias,)),
        scraper.BrowserListing("slattery", seed_only_url, "Historical vehicle", (seed_only_discovery,), (seed_only_url,)),
    ])

    discovered = {listing.url: listing for listing in result.listings}
    seeds = {listing.url: listing for listing in result.seed_listings}
    assert set(discovered) == {NUMERIC, OTHER}
    assert set(seeds) == {NUMERIC, seed_only_url}
    assert seed_only_url not in requested
    assert seeds[NUMERIC] == discovered[NUMERIC]
    assert historical_discovery in discovered[NUMERIC].discovery_urls
    assert len(discovered[NUMERIC].discovery_urls) == 3
    assert historical_alias in discovered[NUMERIC].url_aliases
    assert ALPHA in discovered[NUMERIC].url_aliases
    assert NUMERIC in discovered[NUMERIC].url_aliases
    assert seeds[seed_only_url].discovery_urls == (seed_only_discovery,)
    assert seed_only_discovery not in discovered[NUMERIC].discovery_urls


@pytest.mark.parametrize("bad_response,reason", [
    ((200, [], "<html>Temporarily unavailable</html>"), "unrecognised listing payload"),
    ((200, [], ""), "unrecognised listing payload"),
    ((403, [], "Forbidden"), "HTTP 403"),
    ((500, [], "Error"), "HTTP 500"),
    (api_page(2, [asset()]), "page traversal"),
    (api_page(1, [], total=2, total_pages=2), "empty page"),
])
def test_unknown_empty_blocked_or_wrong_page_is_degraded(bad_response, reason):
    urls = scraper.build_source_list_urls("slattery", 1)
    result, _ = run_discovery({
        urls[0]: bad_response,
        urls[1]: grays_page([], total=0),
    }, pages=1)
    assert result.pagination_exhausted is False
    assert any(reason in note for note in result.incomplete_reasons)
    assert result.blocked_pages == int(bad_response[0] == 403)


def test_page_cap_cannot_certify_complete_discovery():
    urls = scraper.build_source_list_urls("slattery", 1)
    result, _ = run_discovery({
        urls[0]: api_page(1, [asset()]),
        urls[1]: grays_page([[NATIVE_GRAYS, "Grays vehicle"]], total=2, more=True),
    }, pages=1)
    assert result.page_cap_reached is True
    assert result.pagination_exhausted is False
    assert len(result.incomplete_reasons) == 2


@pytest.mark.parametrize("second_page,reason", [
    (api_page(2, [asset()]), "repeated listing"),
    (api_page(2, [], total=2), "advertised total"),
    (api_page(2, [asset(139070, 10727)], total=3), "count changed"),
])
def test_count_reconciliation_detects_duplicate_missing_or_changing_inventory(second_page, reason):
    responses = base_responses()
    responses[scraper.build_source_list_urls("slattery", 2)[1]] = second_page
    result, _ = run_discovery(responses)
    assert result.pagination_exhausted is False
    assert any(reason in note for note in result.incomplete_reasons)


def test_grays_unknown_card_or_missing_pagination_cannot_claim_exhaustion():
    responses = base_responses()
    grays_first = scraper.build_source_list_urls("slattery", 2)[2]
    responses[grays_first] = grays_page([["https://other.example/assets/123", "Unknown operator"]], total=1)
    result, _ = run_discovery(responses)
    assert result.pagination_exhausted is False
    assert any("recognised card count" in note for note in result.incomplete_reasons)


def test_unresolved_alias_remains_separate_and_degrades_discovery():
    responses = base_responses()
    responses[ALPHA] = (200, [], "<html>Missing asset</html>")
    result, _ = run_discovery(responses)
    assert len(result.listings) == 3
    assert any("alias could not be reconciled" in note for note in result.incomplete_reasons)


def test_matching_titles_without_explicit_ids_do_not_merge_auction_urls():
    responses = base_responses()
    responses[ALPHA] = (200, [], alias_html(wrong_auction=True))
    result, _ = run_discovery(responses)
    assert {listing.url for listing in result.listings} == {
        NUMERIC, OTHER, "https://slatteryauctions.com.au/assets/137614?auctionId=10302",
    }


def test_referral_validation_rejects_other_hosts_and_preserves_unknown_query_identity():
    assert scraper._slattery_referral("https://evil.example/assets/137614?auctionId=10301", "https://www.grays.com") == ""
    assert scraper._slattery_referral(NUMERIC + "&identity=separate&utm_source=grays", "https://www.grays.com") == NUMERIC + "&identity=separate"


def test_live_api_contract_snapshot():
    # Public /api/slattery/assets?categoryIds=1&pageNumber=19&pageSize=18
    # captured 2026-09-11. Identifying fields + unmodified metadata retained.
    snapshot = {"ok": True, "status": 200, "data": [{"id": 142304, "auctionId": 10990, "name": "John Deere   Diesel"}],
                "metadata": {"currentPage": 19, "totalPages": 19, "pageSize": 18, "totalCount": 325, "hasPrevious": True, "hasNext": False}}
    rows, metadata = scraper._slattery_api_page(json.dumps(snapshot))
    assert rows[0]["id"] == 142304
    assert metadata["hasNext"] is False


def test_scrape_sources_deduplicates_resolved_seeds_and_audits_missing_seed_evidence(monkeypatch):
    responses = base_responses()
    discovery, _ = run_discovery(responses, seeds=[
        scraper.BrowserListing("slattery", ALPHA),
        scraper.BrowserListing("slattery", "https://slatteryauctions.com.au/assets/999999?auctionId=10301"),
    ])

    class FakePlaywright:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def fake_discover(*_args, **_kwargs):
        return discovery

    requested = []

    async def fake_details(_playwright, listings, **_kwargs):
        requested.extend(listing.url for listing in listings)
        return [{"source": "slattery", "url": listing.url, "scrape_status": "parsed_http_200",
                 "detail_completeness_status": "incomplete" if "999999" in listing.url else "complete"} for listing in listings]

    monkeypatch.setattr("playwright.async_api.async_playwright", FakePlaywright)
    monkeypatch.setattr(scraper, "_discover_source_links_with_browser_recycling", fake_discover)
    monkeypatch.setattr(scraper, "_scrape_detail_batches", fake_details)
    monkeypatch.setattr(scraper, "tag_discovered_links", lambda listings: pd.DataFrame({"url": [listing.url for listing in listings], "selected_for_detail": "1"}))
    _, _, audit = asyncio.run(scraper.scrape_sources(
        ["slattery"], max_list_pages_per_source=2, max_details_per_source=0,
        headless=True, prefilter_list_to_curves=False, detail_timeout_ms=1, detail_wait_ms=0,
    ))
    assert requested.count(NUMERIC) == 1
    assert len(requested) == 3
    assert audit.iloc[0]["completeness_status"] == "incomplete"
    assert "including seeds" in audit.iloc[0]["notes"]
