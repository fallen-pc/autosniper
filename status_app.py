import json
import math
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

METRICS_PATH = Path("status") / "metrics.json"
NOW = datetime.now(timezone.utc)


def load_metrics() -> dict:
    if not METRICS_PATH.exists():
        return {}
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def format_minutes_ago(last_run_utc: str) -> float:
    try:
        ts = datetime.fromisoformat(last_run_utc.replace("Z", "+00:00"))
        return max((NOW - ts).total_seconds() / 60.0, 0.0)
    except Exception:
        return math.inf


st.set_page_config(page_title="Grays Scraper Health", layout="wide")
st.title("🩺 Grays Scraper Health")

metrics = load_metrics()
if not metrics:
    st.error("No metrics found. Run the nightly job once so it writes status/metrics.json.")
    st.stop()

mins_ago = format_minutes_ago(metrics.get("last_run_utc", ""))
active_listings = int(metrics.get("active_listings", 0))
runs_total = int(metrics.get("runs_total", 0))
runs_failed = int(metrics.get("runs_failed", 0))
error_ratio = (runs_failed / max(runs_total, 1)) if runs_total else math.nan
duration_sec = float(metrics.get("duration_sec", 0.0))

STALE_MINUTES = 15
MIN_LISTINGS = 50
MAX_ERROR_RATIO = 0.05
MAX_DURATION_SEC = 15 * 60


def metric_chip(value: str, label: str, healthy: bool) -> None:
    st.metric(label, value)
    st.markdown("✅ Healthy" if healthy else "🟥 Check me")


col1, col2, col3, col4 = st.columns(4)
with col1:
    metric_chip(f"{mins_ago:.1f} min ago", "Last run", mins_ago <= STALE_MINUTES)
with col2:
    metric_chip(f"{active_listings:,}", "Active listings", active_listings >= MIN_LISTINGS)
with col3:
    ratio_display = f"{error_ratio * 100:.2f}%" if not math.isnan(error_ratio) else "N/A"
    metric_chip(ratio_display, "Error ratio", error_ratio <= MAX_ERROR_RATIO)
with col4:
    metric_chip(f"{duration_sec:.1f}s", "Runtime", duration_sec <= MAX_DURATION_SEC)

st.divider()
st.subheader("Run Details")
st.json(metrics)

all_ok = (
    mins_ago <= STALE_MINUTES
    and active_listings >= MIN_LISTINGS
    and error_ratio <= MAX_ERROR_RATIO
    and duration_sec <= MAX_DURATION_SEC
)
if all_ok:
    st.success("All systems go 🚀")
else:
    st.error("Attention needed 🔧")

st.caption("Tip: run_nightly.py writes metrics.json automatically after each run.")
