from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_carsales_apify import (
    ABOTAPI_ACTOR_ID,
    IMPORT_DEFERRED_EXIT_CODE,
    _carsales_url_target,
    _validated_url_targets,
    build_actor_input,
    import_completed_run,
    main,
    poll_run_until_terminal,
    require_token,
    start_actor_run,
)


def test_carsales_url_target_extracts_private_make_and_model():
    assert _carsales_url_target(
        "https://www.carsales.com.au/cars/private/mazda/cx-7/"
    ) == ("mazda", "cx-7")
    assert _carsales_url_target("https://www.carsales.com.au/cars/mazda/cx-7/") is None
    assert _carsales_url_target(
        "https://www.carsales.com.au/other/private/mazda/cx-7/"
    ) is None
    assert _carsales_url_target(
        "https://www.carsales.com.au/cars/private/mazda/cx-7/extra/"
    ) is None
    assert _carsales_url_target(
        "https://evil.test/cars/private/mazda/cx-7/"
    ) is None


def test_validated_url_targets_rejects_unmapped_or_non_carsales_urls():
    with pytest.raises(RuntimeError, match="rejected"):
        _validated_url_targets(
            [
                "https://www.carsales.com.au/cars/private/mazda/cx-7/",
                "https://evil.test/cars/private/mazda/cx-7/",
            ]
        )

    with pytest.raises(RuntimeError, match="rejected"):
        _validated_url_targets(["https://www.carsales.com.au/cars/mazda/cx-7/"])


def test_build_actor_input_uses_url_mode_for_an_exact_start_url():
    actor_input = build_actor_input(
        make="Holden",
        model="Commodore",
        body_type="Sedan",
        transmission="Automatic",
        fuel_type="Petrol",
        state="VIC",
        start_url="https://www.carsales.com.au/cars/holden/commodore/",
    )

    assert actor_input["mode"] == "url"
    assert actor_input["condition"] == "used"
    assert actor_input["sellerType"] == "private"
    assert actor_input["make"] == "holden"
    assert actor_input["model"] == "commodore"
    assert actor_input["bodyType"] == "sedan"
    assert actor_input["transmission"] == "automatic"
    assert actor_input["fuelType"] == "petrol"
    assert actor_input["state"] == "vic"
    assert actor_input["startUrls"] == [{"url": "https://www.carsales.com.au/cars/holden/commodore/"}]
    assert actor_input["proxy"]["apifyProxyGroups"] == ["RESIDENTIAL"]


def test_build_actor_input_uses_search_mode_without_a_start_url():
    actor_input = build_actor_input(make="Toyota", model="RAV4")

    assert actor_input["mode"] == "search"
    assert "startUrls" not in actor_input


def test_build_actor_input_uses_abotapi_schema_and_caps():
    actor_input = build_actor_input(
        make="Nissan",
        model="Pulsar",
        body_type="Sedan",
        transmission="Automatic",
        fuel_type="Petrol",
        actor_id=ABOTAPI_ACTOR_ID,
        max_listings=30,
    )

    assert actor_input["mode"] == "search"
    assert actor_input["make"] == "Nissan"
    assert actor_input["model"] == "Pulsar"
    assert actor_input["bodyType"] == "sedan"
    assert actor_input["maxListings"] == 30
    assert actor_input["expandPriceBands"] is False
    assert actor_input["proxyConfiguration"]["apifyProxyGroups"] == ["RESIDENTIAL"]
    assert "flatten" not in actor_input


def test_build_actor_input_accepts_multiple_exact_abotapi_urls():
    actor_input = build_actor_input(
        actor_id=ABOTAPI_ACTOR_ID,
        start_urls=[
            "https://www.carsales.com.au/cars/private/mazda/cx-3/",
            "https://www.carsales.com.au/cars/private/mitsubishi/asx/",
            "https://www.carsales.com.au/cars/private/mazda/cx-3/",
        ],
        max_listings=500,
    )

    assert actor_input["mode"] == "url"
    assert actor_input["urls"] == [
        "https://www.carsales.com.au/cars/private/mazda/cx-3/",
        "https://www.carsales.com.au/cars/private/mitsubishi/asx/",
    ]
    assert actor_input["maxListings"] == 500


def test_require_token_rejects_missing_token(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="APIFY_TOKEN"):
        require_token("")


def test_start_actor_run_posts_to_apify_with_cost_caps(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"id": "run1", "status": "RUNNING"}}

    def fake_post(url, *, headers, params, json, timeout):
        calls.append(
            {
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
                "timeout": timeout,
            }
        )
        return Response()

    monkeypatch.setattr("scripts.run_carsales_apify.requests.post", fake_post)

    run = start_actor_run(
        {"make": "holden"},
        token="token1",
        max_items=50,
        max_total_charge_usd=2,
        wait_seconds=30,
    )

    assert run["id"] == "run1"
    assert calls[0]["url"].endswith("/acts/memo23~carsales-cheerio/runs")
    assert calls[0]["headers"]["Authorization"] == "Bearer token1"
    assert calls[0]["params"] == {
        "maxItems": 50,
        "maxTotalChargeUsd": 2,
        "waitForFinish": 30,
    }
    assert calls[0]["json"] == {"make": "holden"}


def test_import_completed_run_writes_normalized_rows(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "scripts.run_carsales_apify.fetch_dataset_items",
        lambda dataset_id, token=None: [
            {
                "runId": "run1",
                "adId": "SSE-AD-1",
                "canonicalUrl": "https://example.test/car",
                "title": "2010 Holden Commodore Omega VE Auto MY10",
                "make": "Holden",
                "model": "Commodore",
                "year": 2010,
                "variant": "Omega VE Auto MY10",
                "price": 8500,
                "scrapedAt": "2026-06-19T03:23:13.687Z",
                "specs": {
                    "bodyStyle": "Sedan",
                    "transmission": "Automatic",
                    "fuelType": "Petrol - Unleaded Ulp",
                    "odometer": 137000,
                    "all": {"Series": "VE", "Badge": "Omega"},
                },
                "seller": {"type": "Private"},
            }
        ],
    )
    output_path = tmp_path / "carsales_apify_listings.csv"

    imported_count = import_completed_run(
        {"id": "run1", "status": "SUCCEEDED", "defaultDatasetId": "dataset1"},
        output_path=output_path,
        overwrite=True,
    )

    assert imported_count == 1
    text = output_path.read_text(encoding="utf-8")
    assert "carsales_apify" in text
    assert "SSE-AD-1" in text


def test_import_normalizes_known_toyota_hybrid_series(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "scripts.run_carsales_apify.fetch_dataset_items",
        lambda dataset_id, token=None: [
            {
                "adId": "SSE-AD-RAV4",
                "canonicalUrl": "https://example.test/rav4",
                "title": "2024 Toyota RAV4 GX Auto 2WD",
                "make": "Toyota",
                "model": "RAV4",
                "year": 2024,
                "variant": "GX Auto 2WD",
                "price": 42500,
                "specs": {
                    "bodyStyle": "SUV",
                    "transmission": "Automatic",
                    "fuelType": "",
                    "odometer": 42000,
                    "all": {"Series": "AXAH52R", "Badge": "GX"},
                },
                "seller": {"type": "Private"},
            }
        ],
    )
    output_path = tmp_path / "carsales_apify_listings.csv"

    import_completed_run(
        {"id": "run-rav4", "status": "SUCCEEDED", "defaultDatasetId": "dataset-rav4"},
        output_path=output_path,
        overwrite=True,
    )

    imported = __import__("pandas").read_csv(output_path)
    assert imported.loc[0, "fuel_type"] == "Hybrid"


def test_import_completed_run_can_import_cost_cap_aborted_rows(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "scripts.run_carsales_apify.fetch_dataset_items",
        lambda dataset_id, token=None: [
            {
                "runId": "run1",
                "adId": "SSE-AD-2",
                "canonicalUrl": "https://example.test/partial-car",
                "make": "Holden",
                "model": "Commodore",
                "year": 2012,
                "variant": "Omega VE Series II Auto MY12",
                "price": 3000,
                "scrapedAt": "2026-06-19T03:59:53.747Z",
                "specs": {"bodyStyle": "Wagon", "odometer": 338000, "all": {"Series": "VE Series II"}},
                "seller": {"type": "Private"},
            }
        ],
    )

    imported_count = import_completed_run(
        {"id": "run1", "status": "ABORTED", "defaultDatasetId": "dataset1"},
        output_path=tmp_path / "carsales_apify_listings.csv",
        overwrite=True,
        allow_partial=True,
    )

    assert imported_count == 1


def test_poll_run_until_terminal_fetches_until_succeeded(monkeypatch):
    calls = []
    statuses = iter(
        [
            {"id": "run1", "status": "RUNNING", "defaultDatasetId": "dataset1"},
            {"id": "run1", "status": "SUCCEEDED", "defaultDatasetId": "dataset1"},
        ]
    )

    def fake_fetch(run_id, token=None):
        calls.append((run_id, token))
        return next(statuses)

    monkeypatch.setattr("scripts.run_carsales_apify.fetch_run_metadata", fake_fetch)
    monkeypatch.setattr("scripts.run_carsales_apify.time.sleep", lambda seconds: None)

    final = poll_run_until_terminal(
        {"id": "run1", "status": "READY"},
        token="token1",
        poll_interval_seconds=1,
        max_wait_seconds=10,
    )

    assert final["status"] == "SUCCEEDED"
    assert calls == [("run1", "token1"), ("run1", "token1")]


def test_main_blocks_paid_run_when_preflight_blocks(monkeypatch):
    class Result:
        status = "block"
        target_label = "toyota / camry"
        staging_rows = 50
        already_covered_rows = 50
        newly_supported_rows = 0
        still_unclassified_rows = 0
        already_covered_share = 1.0
        active_uncovered_rows = 0
        buildable_uncovered_groups = 0
        recommendation = "Blocked."

    monkeypatch.setattr(
        "scripts.run_carsales_apify.run_preflight",
        lambda **kwargs: (Result(), __import__("pandas").DataFrame()),
    )

    with pytest.raises(RuntimeError, match="Preflight blocked"):
        main(["--token", "token1", "--make", "toyota", "--model", "camry"])


def test_main_can_override_covered_refresh_preflight(monkeypatch):
    calls = []

    class Result:
        status = "block"
        target_label = "toyota / camry"
        staging_rows = 50
        already_covered_rows = 50
        newly_supported_rows = 0
        still_unclassified_rows = 0
        already_covered_share = 1.0
        active_uncovered_rows = 0
        buildable_uncovered_groups = 0
        recommendation = "Blocked."

    monkeypatch.setattr(
        "scripts.run_carsales_apify.run_preflight",
        lambda **kwargs: (Result(), __import__("pandas").DataFrame()),
    )
    monkeypatch.setattr(
        "scripts.run_carsales_apify.start_actor_run",
        lambda actor_input, **kwargs: calls.append((actor_input, kwargs))
        or {"id": "run1", "status": "RUNNING", "defaultDatasetId": "dataset1"},
    )

    assert main(["--token", "token1", "--make", "toyota", "--model", "camry", "--allow-covered-refresh"]) == 0
    assert calls


def test_main_rejects_invalid_exact_url_even_when_preflight_is_skipped():
    with pytest.raises(RuntimeError, match="Every paid exact URL"):
        main(
            [
                "--token",
                "token1",
                "--start-url",
                "https://evil.test/cars/private/toyota/camry/",
                "--skip-preflight",
            ]
        )


def test_main_returns_distinct_status_when_import_is_deferred(monkeypatch):
    monkeypatch.setattr(
        "scripts.run_carsales_apify.start_actor_run",
        lambda actor_input, **kwargs: {"id": "run1", "status": "RUNNING"},
    )
    monkeypatch.setattr(
        "scripts.run_carsales_apify.poll_run_until_terminal",
        lambda run, **kwargs: run,
    )

    result = main(
        [
            "--token",
            "token1",
            "--make",
            "toyota",
            "--model",
            "camry",
            "--skip-preflight",
            "--import-results",
        ]
    )

    assert result == IMPORT_DEFERRED_EXIT_CODE
