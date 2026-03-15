"""Scraper and pipeline health reporting helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from shared.data_loader import dataset_path


DEFAULT_HEALTH_REPORT_DIR = Path("output/health")
SCRAPER_HEALTH_JSON_PATH = DEFAULT_HEALTH_REPORT_DIR / "scraper_health.json"
SCRAPER_FAILURES_CSV_PATH = DEFAULT_HEALTH_REPORT_DIR / "scraper_failure_reasons.csv"
LEGACY_FAILURES_PATH = dataset_path("scrape_failures.csv")

DATASET_CONFIG: dict[str, dict[str, Any]] = {
    "links": {
        "path": dataset_path("all_vehicle_links.csv"),
        "threshold_minutes": 24 * 60,
        "label": "Links",
        "allow_zero": False,
    },
    "static": {
        "path": dataset_path("vehicle_static_details.csv"),
        "threshold_minutes": 24 * 60,
        "label": "Static",
        "allow_zero": False,
    },
    "active": {
        "path": dataset_path("active_vehicle_details.csv"),
        "threshold_minutes": 120,
        "label": "Active",
        "allow_zero": False,
    },
    "valuations": {
        "path": dataset_path("ai_listing_valuations.csv"),
        "threshold_minutes": 120,
        "label": "Valuations",
        "allow_zero": False,
    },
    "sold": {
        "path": dataset_path("sold_cars.csv"),
        "threshold_minutes": 24 * 60,
        "label": "Sold",
        "allow_zero": True,
    },
    "referred": {
        "path": dataset_path("referred_cars.csv"),
        "threshold_minutes": 24 * 60,
        "label": "Referred",
        "allow_zero": True,
    },
    "excluded": {
        "path": dataset_path("excluded_listings.csv"),
        "threshold_minutes": 24 * 60,
        "label": "Excluded",
        "allow_zero": True,
    },
}


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except (ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def _file_age_minutes(path: Path) -> float | None:
    if not path.exists():
        return None
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return round((datetime.now(timezone.utc) - modified).total_seconds() / 60.0, 2)


def _file_modified_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return modified.isoformat()


def _stage_status(count: int, age_minutes: float | None, threshold_minutes: int, *, allow_zero: bool) -> str:
    if age_minutes is None:
        return "failure"
    if not allow_zero and count <= 0:
        return "partial"
    if age_minutes > threshold_minutes * 2:
        return "failure"
    if age_minutes > threshold_minutes:
        return "partial"
    return "healthy"


def _top_failure_reasons() -> pd.DataFrame:
    failures_path = dataset_path("excluded_listings.csv")
    path = failures_path if failures_path.exists() else LEGACY_FAILURES_PATH
    if not path.exists():
        return pd.DataFrame(columns=["reason_code", "count"])
    try:
        df = pd.read_csv(path, usecols=["reason_code"], low_memory=False)
    except Exception:
        return pd.DataFrame(columns=["reason_code", "count"])
    if df.empty or "reason_code" not in df.columns:
        return pd.DataFrame(columns=["reason_code", "count"])
    counts = (
        df["reason_code"]
        .fillna("Unknown")
        .astype(str)
        .str.strip()
        .replace("", "Unknown")
        .value_counts()
        .head(20)
        .rename_axis("reason_code")
        .reset_index(name="count")
    )
    return counts


def build_scraper_health_snapshot(
    *,
    job_name: str | None = None,
    job_status: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    dataset_metrics: dict[str, dict[str, Any]] = {}
    stale_datasets: list[str] = []

    for key, config in DATASET_CONFIG.items():
        path = Path(config["path"])
        frame = _load_csv(path)
        count = int(len(frame))
        age_minutes = _file_age_minutes(path)
        status = _stage_status(
            count,
            age_minutes,
            int(config["threshold_minutes"]),
            allow_zero=bool(config["allow_zero"]),
        )
        if status != "healthy":
            stale_datasets.append(key)
        dataset_metrics[key] = {
            "label": str(config["label"]),
            "path": str(path).replace("\\", "/"),
            "count": count,
            "age_minutes": age_minutes,
            "threshold_minutes": int(config["threshold_minutes"]),
            "status": status,
            "last_modified_at": _file_modified_iso(path),
        }

    active_df = _load_csv(Path(DATASET_CONFIG["active"]["path"]))
    status_mix: dict[str, int] = {}
    if not active_df.empty and "status" in active_df.columns:
        status_counts = (
            active_df["status"]
            .fillna("Unknown")
            .astype(str)
            .str.strip()
            .replace("", "Unknown")
            .value_counts()
        )
        status_mix = {str(key): int(value) for key, value in status_counts.items()}

    stage_metrics = {
        "links_scraped": {
            "label": "Links scraped",
            "count": dataset_metrics["links"]["count"],
            "status": dataset_metrics["links"]["status"],
            "source": "links",
        },
        "vehicles_normalized": {
            "label": "Vehicles normalized",
            "count": dataset_metrics["static"]["count"],
            "status": dataset_metrics["static"]["status"],
            "source": "static",
        },
        "vehicles_excluded": {
            "label": "Vehicles excluded",
            "count": dataset_metrics["excluded"]["count"],
            "status": dataset_metrics["excluded"]["status"],
            "source": "excluded",
        },
        "vehicles_analysed": {
            "label": "Vehicles analysed",
            "count": dataset_metrics["valuations"]["count"],
            "status": dataset_metrics["valuations"]["status"],
            "source": "valuations",
        },
    }

    failure_reasons_df = _top_failure_reasons()
    failure_reasons = failure_reasons_df.to_dict(orient="records")
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": generated_at,
        "job_name": job_name or "",
        "job_status": job_status or "",
        "error_message": error_message or "",
        "dataset_metrics": dataset_metrics,
        "stage_metrics": stage_metrics,
        "active_status_mix": status_mix,
        "stale_datasets": stale_datasets,
        "top_failure_reasons": failure_reasons,
    }


def write_scraper_health_report(
    *,
    report_dir: Path = DEFAULT_HEALTH_REPORT_DIR,
    job_name: str | None = None,
    job_status: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    snapshot = build_scraper_health_snapshot(
        job_name=job_name,
        job_status=job_status,
        error_message=error_message,
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / SCRAPER_HEALTH_JSON_PATH.name
    csv_path = report_dir / SCRAPER_FAILURES_CSV_PATH.name
    json_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    pd.DataFrame(snapshot["top_failure_reasons"]).to_csv(csv_path, index=False)
    snapshot["paths"] = {
        "json": json_path,
        "failure_reasons_csv": csv_path,
    }
    return snapshot


def load_scraper_health_report(report_path: Path = SCRAPER_HEALTH_JSON_PATH) -> dict[str, Any] | None:
    if not report_path.exists():
        return None
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
