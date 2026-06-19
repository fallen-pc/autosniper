from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_carsales_apify import (
    build_actor_input,
    import_completed_run,
    poll_run_until_terminal,
    require_token,
    start_actor_run,
)


def test_build_actor_input_uses_targeted_private_used_filters():
    actor_input = build_actor_input(
        make="Holden",
        model="Commodore",
        body_type="Sedan",
        transmission="Automatic",
        fuel_type="Petrol",
        state="VIC",
        start_url="https://www.carsales.com.au/cars/holden/commodore/",
    )

    assert actor_input["mode"] == "search"
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
