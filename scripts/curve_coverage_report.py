from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from governance.curve_coverage_report import *  # noqa: F401,F403
from governance.curve_coverage_report import main


if __name__ == "__main__":
    main()
