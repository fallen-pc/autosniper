from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from ops.render_curve_images import *  # noqa: F401,F403
from ops.render_curve_images import main


if __name__ == "__main__":
    main()
