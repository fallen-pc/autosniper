"""Compatibility wrapper for the project memory entrypoint."""

from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.project_memory import *  # noqa: F401,F403
from shared.project_memory import main


if __name__ == "__main__":
    raise SystemExit(main())
