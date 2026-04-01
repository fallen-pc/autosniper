from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from ops.analyze_bid_history import *  # noqa: F401,F403
from ops.analyze_bid_history import main


if __name__ == "__main__":
    main()
