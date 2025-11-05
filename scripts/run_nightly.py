import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from scripts import extract_links, extract_vehicle_details, update_bids, update_master
from scripts.outcome_tracking import compute_outcome_metrics
from shared.data_loader import DATA_DIR

METRICS_PATH = ROOT_DIR / "status" / "metrics.json"
ACTIVE_CSV_PATH = DATA_DIR / "active_vehicle_details.csv"


def _load_existing_metrics() -> Dict[str, Any]:
    if not METRICS_PATH.exists():
        return {}
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _count_active_listings() -> Optional[int]:
    if not ACTIVE_CSV_PATH.exists():
        return None
    try:
        import pandas as pd

        df = pd.read_csv(ACTIVE_CSV_PATH)
        return int(len(df))
    except Exception:
        return None


def _write_metrics(success: bool, duration_sec: float, active_listings: Optional[int]) -> None:
    metrics = _load_existing_metrics()
    runs_total = int(metrics.get("runs_total", 0)) + 1
    runs_failed = int(metrics.get("runs_failed", 0)) + (0 if success else 1)
    payload = {
        "last_run_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "active_listings": int(active_listings) if active_listings is not None else int(metrics.get("active_listings", 0)),
        "runs_total": runs_total,
        "runs_failed": runs_failed,
        "duration_sec": float(duration_sec),
    }
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run_pipeline() -> None:
    extract_links.extract_all_vehicle_links()
    asyncio.run(extract_vehicle_details.main())
    update_master.update_master_database()
    asyncio.run(update_bids.update_bids())
    compute_outcome_metrics()


def main() -> None:
    start = time.time()
    try:
        _run_pipeline()
    except Exception:
        duration = time.time() - start
        active_listings = _count_active_listings()
        _write_metrics(success=False, duration_sec=duration, active_listings=active_listings)
        raise
    else:
        duration = time.time() - start
        active_listings = _count_active_listings()
        _write_metrics(success=True, duration_sec=duration, active_listings=active_listings)


if __name__ == "__main__":
    main()
