from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.calibration import DEFAULT_OUTPUT_DIR, write_calibration_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build AutoSniper valuation calibration reports.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for fast smoke checks.")
    parser.add_argument(
        "--no-repairs",
        action="store_true",
        help="Run the calibration without repair/risk repair deductions.",
    )
    args = parser.parse_args(argv)

    paths = write_calibration_report(
        output_dir=args.output_dir,
        include_repairs=not args.no_repairs,
        limit=args.limit,
    )
    print(f"[calibration] wrote detail: {paths.detail_csv}")
    print(f"[calibration] wrote summary: {paths.summary_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
