"""Import Carsales listings from an Apify actor run into a normalized CSV."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import requests

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.data_loader import dataset_path
else:  # pragma: no cover
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.data_loader import dataset_path


APIFY_API_BASE = "https://api.apify.com/v2"
DEFAULT_OUTPUT_PATH = dataset_path("quality/carsales_apify_listings.csv")

OUTPUT_COLUMNS = [
    "run_id",
    "dataset_id",
    "scraped_at",
    "source",
    "ad_id",
    "url",
    "title",
    "make",
    "model",
    "year",
    "badge",
    "series",
    "model_year",
    "variant",
    "price",
    "odometer",
    "body_type",
    "transmission",
    "fuel_type",
    "engine",
    "seller_type",
    "state",
    "region",
    "suburb",
    "market_indicator",
    "price_assessment",
]


def _headers(token: str | None = None) -> dict[str, str]:
    token_value = (token or os.getenv("APIFY_TOKEN") or "").strip()
    if not token_value:
        return {}
    return {"Authorization": f"Bearer {token_value}"}


def _get_json(url: str, *, token: str | None = None) -> Any:
    response = requests.get(url, headers=_headers(token), timeout=60)
    response.raise_for_status()
    return response.json()


def fetch_run_metadata(run_id: str, *, token: str | None = None) -> dict[str, Any]:
    payload = _get_json(f"{APIFY_API_BASE}/actor-runs/{run_id}", token=token)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError(f"Apify run metadata did not contain a data object: {run_id}")
    return data


def fetch_dataset_items(dataset_id: str, *, token: str | None = None) -> list[dict[str, Any]]:
    payload = _get_json(
        f"{APIFY_API_BASE}/datasets/{dataset_id}/items?format=json&clean=true",
        token=token,
    )
    if not isinstance(payload, list):
        raise ValueError(f"Apify dataset did not return a list of items: {dataset_id}")
    return [item for item in payload if isinstance(item, dict)]


def _nested_text(mapping: dict[str, Any], *keys: str) -> str:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _numeric(value: Any) -> Any:
    if value is None or value == "":
        return pd.NA
    return pd.to_numeric(value, errors="coerce")


def _normalise_fuel_type(raw_fuel: str, series: str) -> str:
    series_code = str(series or "").strip().upper()
    if series_code.startswith(("AXAH", "AXVH", "ZWE")):
        return "Hybrid"
    return str(raw_fuel or "").strip()


def _flat_spec_pairs(item: dict[str, Any]) -> dict[str, Any]:
    pairs = item.get("specPairs")
    return pairs if isinstance(pairs, dict) else {}


def _flat_series(item: dict[str, Any]) -> str:
    explicit = str(item.get("series") or "").strip()
    if explicit:
        return explicit
    description = str(item.get("spec") or item.get("overview") or "").strip()
    match = re.match(r"^(.+?)\s+MY\d", description, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def normalize_items(
    items: list[dict[str, Any]], *, run_id: str = "", dataset_id: str = ""
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in items:
        specs = item.get("specs") if isinstance(item.get("specs"), dict) else {}
        spec_all = specs.get("all") if isinstance(specs.get("all"), dict) else {}
        seller = item.get("seller") if isinstance(item.get("seller"), dict) else {}
        location = item.get("location") if isinstance(item.get("location"), dict) else {}
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        flat_pairs = _flat_spec_pairs(item)
        series = _nested_text(spec_all, "Series") or _flat_series(item)
        raw_fuel = str(
            specs.get("fuelType")
            or _nested_text(spec_all, "Fuel Type")
            or item.get("fuelType")
            or item.get("fuel_type")
            or flat_pairs.get("Fuel Type")
            or ""
        ).strip()

        rows.append(
            {
                "run_id": run_id or str(item.get("runId") or "").strip(),
                "dataset_id": dataset_id,
                "scraped_at": str(item.get("scrapedAt") or "").strip(),
                "source": "carsales_apify",
                "ad_id": str(
                    item.get("adId")
                    or item.get("listingId")
                    or item.get("networkId")
                    or ""
                ).strip(),
                "url": str(
                    item.get("canonicalUrl")
                    or item.get("url")
                    or item.get("link")
                    or ""
                ).strip(),
                "title": str(item.get("title") or item.get("name") or "").strip(),
                "make": str(item.get("make") or "").strip(),
                "model": str(item.get("model") or "").strip(),
                "year": _numeric(item.get("year")),
                "badge": (
                    _nested_text(spec_all, "Badge")
                    or str(specs.get("badge") or item.get("badge") or "").strip()
                ),
                "series": series,
                "model_year": (
                    _nested_text(spec_all, "Model Year")
                    or _nested_text(spec_all, "Model year")
                    or str(flat_pairs.get("Model year") or item.get("model_year") or "").strip()
                ),
                "variant": str(item.get("variant") or "").strip(),
                "price": _numeric(item.get("price")),
                "odometer": _numeric(
                    specs.get("odometer")
                    or item.get("odometer")
                    or item.get("odometerKm")
                    or item.get("kms")
                ),
                "body_type": str(
                    specs.get("bodyStyle")
                    or specs.get("categoryType")
                    or item.get("bodyStyle")
                    or item.get("bodyType")
                    or item.get("body_style")
                    or item.get("categoryType")
                    or ""
                ).strip(),
                "transmission": str(
                    specs.get("transmission")
                    or _nested_text(spec_all, "Gear Type")
                    or item.get("transmission")
                    or flat_pairs.get("Transmission")
                    or ""
                ).strip(),
                "fuel_type": _normalise_fuel_type(raw_fuel, series),
                "engine": (
                    _nested_text(spec_all, "Engine")
                    or _nested_text(spec_all, "Engine Size (L)")
                    or str(
                        flat_pairs.get("Engine")
                        or item.get("engine")
                        or item.get("engineSizeL")
                        or ""
                    ).strip()
                ),
                "seller_type": str(
                    seller.get("type") or item.get("sellerType") or item.get("seller_type") or ""
                ).strip(),
                "state": str(location.get("state") or item.get("state") or item.get("Location") or "").strip(),
                "region": str(location.get("region") or item.get("region") or item.get("Region") or "").strip(),
                "suburb": str(location.get("suburb") or item.get("suburb") or "").strip(),
                "market_indicator": str(
                    item.get("marketIndicator") or item.get("priceAssessment") or ""
                ).strip(),
                "price_assessment": str(
                    meta.get("priceAssessment") or item.get("priceAssessment") or ""
                ).strip(),
            }
        )

    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    for column in ["year", "price", "odometer"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").astype("Int64")
    for column in OUTPUT_COLUMNS:
        if column not in {"year", "price", "odometer"}:
            df[column] = df[column].fillna("").astype(str).str.strip()
    return df


def merge_output(existing_path: Path, imported: pd.DataFrame) -> pd.DataFrame:
    if existing_path.exists():
        existing = pd.read_csv(existing_path, low_memory=False)
        for column in OUTPUT_COLUMNS:
            if column not in existing.columns:
                existing[column] = ""
        existing["_merge_order"] = 0
        imported = imported.copy()
        imported["_merge_order"] = 1
        combined = pd.concat(
            [existing[OUTPUT_COLUMNS + ["_merge_order"]], imported[OUTPUT_COLUMNS + ["_merge_order"]]],
            ignore_index=True,
        )
    else:
        combined = imported[OUTPUT_COLUMNS].copy()
        combined["_merge_order"] = 1
    combined["_sort_scraped_at"] = combined["scraped_at"].fillna("").astype(str)
    combined = combined.sort_values(["_sort_scraped_at", "_merge_order"])
    stable_identity = (
        combined["ad_id"].fillna("").astype(str).str.strip()
        + "|"
        + combined["url"].fillna("").astype(str).str.strip()
    )
    identified = combined[stable_identity != "|"].copy()
    unidentified = combined[stable_identity == "|"].copy()
    identified = identified.drop_duplicates(subset=["ad_id", "url"], keep="last")
    combined = pd.concat([identified, unidentified], ignore_index=True)
    combined = combined.drop(columns=["_sort_scraped_at", "_merge_order"]).sort_values(
        ["make", "model", "series", "badge", "year", "odometer", "price"],
        na_position="last",
    )
    return combined.reset_index(drop=True)


def load_items_from_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON array in {path}")
    return [item for item in payload if isinstance(item, dict)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", help="Apify actor run ID to import.")
    parser.add_argument("--dataset-id", help="Apify dataset ID. If omitted, resolved from --run-id.")
    parser.add_argument("--source-json", type=Path, help="Local Apify dataset JSON file to normalize.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--overwrite", action="store_true", help="Overwrite instead of merging by ad/url.")
    parser.add_argument("--token", default="", help="Optional Apify token. Defaults to APIFY_TOKEN.")
    args = parser.parse_args(argv)

    run_id = (args.run_id or "").strip()
    dataset_id = (args.dataset_id or "").strip()
    if args.source_json:
        items = load_items_from_json(args.source_json)
    else:
        if not run_id and not dataset_id:
            parser.error("Provide --run-id, --dataset-id, or --source-json.")
        if run_id and not dataset_id:
            metadata = fetch_run_metadata(run_id, token=args.token)
            dataset_id = str(metadata.get("defaultDatasetId") or "").strip()
            if not dataset_id:
                raise ValueError(f"Run {run_id} did not expose defaultDatasetId")
        items = fetch_dataset_items(dataset_id, token=args.token)

    imported = normalize_items(items, run_id=run_id, dataset_id=dataset_id)
    output = imported if args.overwrite else merge_output(args.output, imported)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(output, args.output, index=False)
    print(f"Imported {len(imported)} Carsales Apify rows into {args.output} ({len(output)} total rows).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
