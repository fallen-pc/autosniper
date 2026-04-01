"""Compatibility wrapper for jobs.normalize_conditions."""

from __future__ import annotations

from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from jobs.normalize_conditions import *  # noqa: F401,F403
from jobs.normalize_conditions import main


if __name__ == "__main__":
    main()
