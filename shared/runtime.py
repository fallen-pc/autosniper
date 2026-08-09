"""Runtime environment helpers shared by the Streamlit entrypoints."""

from __future__ import annotations

import os
from pathlib import Path

VPS_MODE_ENV = "AUTOSNIPER_VPS_MODE"
VPS_ROOT = Path("/opt/autosniper")


def is_vps_runtime() -> bool:
    """Return True when the app is running on the hosted VPS deployment."""
    explicit = os.getenv(VPS_MODE_ENV, "").strip().lower()
    if explicit:
        return explicit in {"1", "true", "yes", "on"}
    return Path(__file__).resolve().parents[1] == VPS_ROOT
