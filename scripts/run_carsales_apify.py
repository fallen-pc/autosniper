"""Start a Carsales Apify scrape run and optionally import the results."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote, unquote, urlparse

import requests

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.import_carsales_apify_run import (
        APIFY_API_BASE,
        DEFAULT_OUTPUT_PATH,
        fetch_run_metadata,
        fetch_dataset_items,
        merge_output,
        normalize_items,
    )
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from scripts.carsales_scrape_preflight import run_preflight
else:  # pragma: no cover
    from scripts.import_carsales_apify_run import (
        APIFY_API_BASE,
        DEFAULT_OUTPUT_PATH,
        fetch_run_metadata,
        fetch_dataset_items,
        merge_output,
        normalize_items,
    )
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from scripts.carsales_scrape_preflight import run_preflight


DEFAULT_ACTOR_ID = "memo23~carsales-cheerio"
ABOTAPI_ACTOR_ID = "abotapi~carsales-au-scraper"
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
EXPAND_PRICE_BANDS_THRESHOLD = 75
IMPORT_DEFERRED_EXIT_CODE = 3
ALLOWED_CARSALES_HOSTS = {"carsales.com.au", "www.carsales.com.au"}


def require_token(token: str | None = None) -> str:
    token_value = (token or os.getenv("APIFY_TOKEN") or "").strip()
    if not token_value:
        raise RuntimeError("Set APIFY_TOKEN or pass --token before starting an Apify run.")
    return token_value


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def build_actor_input(
    *,
    make: str = "",
    model: str = "",
    body_type: str = "",
    condition: str = "used",
    seller_type: str = "private",
    transmission: str = "",
    fuel_type: str = "",
    state: str = "",
    sort_by: str = "featured",
    start_url: str = "",
    start_urls: Sequence[str] | None = None,
    flatten: bool = False,
    residential_proxy: bool = True,
    actor_id: str = DEFAULT_ACTOR_ID,
    max_listings: int = 50,
) -> dict[str, Any]:
    exact_urls = [
        str(url).strip()
        for url in ([start_url] if start_url else []) + list(start_urls or [])
        if str(url).strip()
    ]
    exact_urls = list(dict.fromkeys(exact_urls))
    if actor_id == ABOTAPI_ACTOR_ID:
        actor_input = {
            "mode": "url" if exact_urls else "search",
            "condition": condition,
            "sellerType": seller_type,
            "sortBy": str(sort_by or "featured").replace("_", "-"),
            "make": str(make or "").strip(),
            "model": str(model or "").strip(),
            "bodyType": str(body_type or "").strip().lower(),
            "transmission": str(transmission or "").strip().lower(),
            "fuelType": str(fuel_type or "").strip().lower(),
            "state": str(state or "").strip().lower(),
            "fetchDetails": False,
            "expandPriceBands": int(max_listings) > EXPAND_PRICE_BANDS_THRESHOLD,
            "maxListings": int(max_listings),
            "maxPages": 20,
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],
            },
        }
        if exact_urls:
            actor_input["urls"] = exact_urls
        return actor_input

    actor_input: dict[str, Any] = {
        "mode": "url" if exact_urls else "search",
        "condition": condition,
        "sellerType": seller_type,
        "sortBy": sort_by,
        "flatten": flatten,
        "skipPriceSplitting": False,
        "monitoringMode": False,
        "monitoringWindow": "since-last-run",
        "maxConcurrency": 5,
        "minConcurrency": 1,
        "maxRequestRetries": 5,
    }
    for key, value in {
        "make": make,
        "model": model,
        "bodyType": body_type,
        "transmission": transmission,
        "fuelType": fuel_type,
        "state": state,
    }.items():
        actor_input[key] = str(value or "").strip().lower()
    if exact_urls:
        actor_input["startUrls"] = [{"url": url} for url in exact_urls]
    if residential_proxy:
        actor_input["proxy"] = {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}
    else:
        actor_input["proxy"] = {"useApifyProxy": True}
    return actor_input


def start_actor_run(
    actor_input: dict[str, Any],
    *,
    actor_id: str = DEFAULT_ACTOR_ID,
    token: str | None = None,
    max_items: int = 50,
    max_total_charge_usd: float = 2.0,
    wait_seconds: int = 0,
    memory_mbytes: int | None = None,
) -> dict[str, Any]:
    token_value = require_token(token)
    encoded_actor_id = quote(actor_id, safe="~")
    params: dict[str, Any] = {
        "maxItems": max_items,
        "maxTotalChargeUsd": max_total_charge_usd,
    }
    if wait_seconds > 0:
        params["waitForFinish"] = wait_seconds
    if memory_mbytes:
        params["memory"] = memory_mbytes

    response = requests.post(
        f"{APIFY_API_BASE}/acts/{encoded_actor_id}/runs",
        headers=_headers(token_value),
        params=params,
        json=actor_input,
        timeout=max(60, wait_seconds + 10),
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("Apify run response did not contain a data object.")
    return data


def import_completed_run(
    run: dict[str, Any],
    *,
    token: str | None = None,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    overwrite: bool = False,
    allow_partial: bool = False,
) -> int:
    run_id = str(run.get("id") or "").strip()
    dataset_id = str(run.get("defaultDatasetId") or "").strip()
    status = str(run.get("status") or "").strip().upper()
    importable_statuses = {"SUCCEEDED"}
    if allow_partial:
        importable_statuses.update({"ABORTED", "TIMED-OUT"})
    if status not in importable_statuses:
        raise RuntimeError(f"Run {run_id or '<unknown>'} is not importable yet: status={status or '<blank>'}")
    if not dataset_id:
        raise RuntimeError(f"Run {run_id} did not expose defaultDatasetId.")
    items = fetch_dataset_items(dataset_id, token=token)
    imported = normalize_items(items, run_id=run_id, dataset_id=dataset_id)
    output = imported if overwrite else merge_output(output_path, imported)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(output, output_path, index=False)
    return len(imported)


def poll_run_until_terminal(
    run: dict[str, Any],
    *,
    token: str | None = None,
    poll_interval_seconds: int = 20,
    max_wait_seconds: int = 600,
) -> dict[str, Any]:
    run_id = str(run.get("id") or "").strip()
    if not run_id:
        raise RuntimeError("Cannot poll Apify run without an id.")
    deadline = time.monotonic() + max(0, max_wait_seconds)
    current = dict(run)
    while str(current.get("status") or "").strip().upper() not in TERMINAL_STATUSES:
        if time.monotonic() >= deadline:
            return current
        time.sleep(max(1, poll_interval_seconds))
        current = fetch_run_metadata(run_id, token=token)
    return current


def _print_run_summary(run: dict[str, Any]) -> None:
    print(f"run_id={run.get('id', '')}")
    print(f"status={run.get('status', '')}")
    print(f"dataset_id={run.get('defaultDatasetId', '')}")
    if run.get("usageTotalUsd") is not None:
        print(f"usage_total_usd={run.get('usageTotalUsd')}")
    if run.get("consoleUrl"):
        print(f"console_url={run.get('consoleUrl')}")


def _carsales_url_target(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() not in ALLOWED_CARSALES_HOSTS:
        return None
    parts = [unquote(part).strip() for part in parsed.path.split("/") if part.strip()]
    if len(parts) != 4 or [part.lower() for part in parts[:2]] != ["cars", "private"]:
        return None
    return parts[2], parts[3]


def _validated_url_targets(urls: Sequence[str]) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    invalid_urls: list[str] = []
    for url in urls:
        target = _carsales_url_target(url)
        if target is None:
            invalid_urls.append(url)
        else:
            targets.append(target)
    if invalid_urls:
        raise RuntimeError(
            "Every paid exact URL must be an HTTPS Carsales private make/model URL; rejected: "
            + ", ".join(invalid_urls)
        )
    return targets


def _run_paid_scrape_preflight(args: argparse.Namespace) -> None:
    exact_urls = list(getattr(args, "start_urls", []) or [])
    if args.start_url:
        exact_urls.insert(0, args.start_url)
    url_targets = _validated_url_targets(exact_urls)
    targets = url_targets or [(args.make, args.model)]
    results = []
    for target_make, target_model in targets:
        result, summary = run_preflight(
            make=target_make,
            model=target_model,
            body_type=args.body_type,
            transmission=args.transmission,
            fuel_type=args.fuel_type,
            state=args.state,
            seller_type=args.seller_type,
            min_new_lane_rows=args.preflight_min_new_lane_rows,
            max_already_covered_share=args.preflight_max_already_covered_share,
        )
        results.append(result)
        print(f"preflight_status={result.status}")
        print(f"preflight_target={result.target_label}")
        print(f"preflight_staging_rows={result.staging_rows}")
        print(f"preflight_already_covered_rows={result.already_covered_rows}")
        print(f"preflight_newly_supported_rows={result.newly_supported_rows}")
        print(f"preflight_still_unclassified_rows={result.still_unclassified_rows}")
        print(f"preflight_already_covered_share={result.already_covered_share}")
        print(f"preflight_active_uncovered_rows={result.active_uncovered_rows}")
        print(f"preflight_buildable_uncovered_groups={result.buildable_uncovered_groups}")
        print(f"preflight_recommendation={result.recommendation}")
        if not summary.empty:
            print("preflight_top_local_groups:")
            print(summary.to_string(index=False))
    if any(result.status == "block" for result in results) and not args.allow_covered_refresh:
        raise RuntimeError(
            "Preflight blocked this paid scrape because it appears to duplicate existing curve coverage. "
            "Pass --allow-covered-refresh only for an intentional refresh, extension, or validation run."
        )
    if any(result.status == "warn" for result in results) and not args.allow_preflight_warning and not args.allow_covered_refresh:
        raise RuntimeError(
            "Preflight warned on this paid scrape. Narrow the target or pass --allow-preflight-warning "
            "after confirming the expected curve-coverage yield."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID)
    parser.add_argument("--token", default="", help="Optional Apify token. Defaults to APIFY_TOKEN.")
    parser.add_argument("--make", default="", help="Carsales make filter, e.g. holden.")
    parser.add_argument("--model", default="", help="Carsales model filter, e.g. commodore.")
    parser.add_argument("--body-type", default="", help="Carsales body type filter, e.g. sedan.")
    parser.add_argument("--condition", default="used")
    parser.add_argument("--seller-type", default="private")
    parser.add_argument("--transmission", default="")
    parser.add_argument("--fuel-type", default="")
    parser.add_argument("--state", default="")
    parser.add_argument("--sort-by", default="featured")
    parser.add_argument("--start-url", default="", help="Optional exact Carsales search URL.")
    parser.add_argument(
        "--start-url-file",
        type=Path,
        help="Optional UTF-8 text file containing one exact Carsales search URL per line.",
    )
    parser.add_argument("--max-items", type=int, default=50)
    parser.add_argument("--max-total-charge-usd", type=float, default=2.0)
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--poll-until-finished", action="store_true")
    parser.add_argument("--poll-interval-seconds", type=int, default=20)
    parser.add_argument("--poll-max-wait-seconds", type=int, default=600)
    parser.add_argument("--memory-mbytes", type=int, default=0)
    parser.add_argument("--no-residential-proxy", action="store_true")
    parser.add_argument("--flatten", action="store_true")
    parser.add_argument("--import-results", action="store_true")
    parser.add_argument(
        "--import-partial",
        action="store_true",
        help="Allow importing persisted rows from ABORTED or TIMED-OUT runs, useful when a cost cap stops the actor.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip the local coverage preflight. Avoid this for paid runs.",
    )
    parser.add_argument(
        "--allow-preflight-warning",
        action="store_true",
        help="Allow a paid run when preflight returns warn after manual review.",
    )
    parser.add_argument(
        "--allow-covered-refresh",
        action="store_true",
        help="Allow a paid run that mostly refreshes or extends already covered lanes.",
    )
    parser.add_argument("--preflight-min-new-lane-rows", type=int, default=10)
    parser.add_argument("--preflight-max-already-covered-share", type=float, default=0.35)
    args = parser.parse_args(argv)
    start_urls: list[str] = []
    if args.start_url_file:
        start_urls = [
            line.strip()
            for line in args.start_url_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if not start_urls:
            parser.error("--start-url-file did not contain any Carsales URLs")
    args.start_urls = start_urls

    exact_urls = ([args.start_url] if args.start_url else []) + start_urls
    if exact_urls:
        _validated_url_targets(exact_urls)

    if not args.skip_preflight:
        _run_paid_scrape_preflight(args)

    actor_input = build_actor_input(
        make=args.make,
        model=args.model,
        body_type=args.body_type,
        condition=args.condition,
        seller_type=args.seller_type,
        transmission=args.transmission,
        fuel_type=args.fuel_type,
        state=args.state,
        sort_by=args.sort_by,
        start_url=args.start_url,
        start_urls=start_urls,
        flatten=args.flatten,
        residential_proxy=not args.no_residential_proxy,
        actor_id=args.actor_id,
        max_listings=args.max_items,
    )
    run = start_actor_run(
        actor_input,
        actor_id=args.actor_id,
        token=args.token,
        max_items=args.max_items,
        max_total_charge_usd=args.max_total_charge_usd,
        wait_seconds=args.wait_seconds,
        memory_mbytes=args.memory_mbytes or None,
    )
    _print_run_summary(run)
    if args.poll_until_finished or args.import_results:
        run = poll_run_until_terminal(
            run,
            token=args.token,
            poll_interval_seconds=args.poll_interval_seconds,
            max_wait_seconds=args.poll_max_wait_seconds,
        )
        print("final_run:")
        _print_run_summary(run)
    if args.import_results:
        status = str(run.get("status") or "").strip().upper()
        if status not in TERMINAL_STATUSES:
            print(
                "import_deferred=true "
                f"reason=run_still_{status.lower() or 'unknown'} "
                "rerun scripts/import_carsales_apify_run.py after the actor reaches a terminal status"
            )
            return IMPORT_DEFERRED_EXIT_CODE
        imported_count = import_completed_run(
            run,
            token=args.token,
            output_path=args.output,
            overwrite=args.overwrite,
            allow_partial=args.import_partial,
        )
        print(f"imported_rows={imported_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
