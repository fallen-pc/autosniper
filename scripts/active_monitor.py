from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from ops import active_monitor as _active_monitor

sys.modules[__name__] = _active_monitor
