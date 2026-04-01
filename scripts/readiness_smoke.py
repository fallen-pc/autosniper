from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from governance.readiness_smoke import *  # noqa: F401,F403
from governance.readiness_smoke import main


if __name__ == "__main__":
    raise SystemExit(main())
