from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.repair_ai_classifier import AI_SUGGESTIONS_PATH, classify_repair_review_queue
from shared.repair_review import LIVE_QUEUE_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify Repair Review queue items with OpenAI suggestions.")
    parser.add_argument("--queue", type=Path, default=LIVE_QUEUE_PATH)
    parser.add_argument("--output", type=Path, default=AI_SUGGESTIONS_PATH)
    parser.add_argument("--model", default=None)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = classify_repair_review_queue(
        queue_path=args.queue,
        output_path=args.output,
        model=args.model,
        limit=args.limit,
        force=args.force,
        dry_run=args.dry_run,
    )
    if result.skipped_reason:
        print(f"repair_ai_classifier_skipped={result.skipped_reason}")
        return 0
    print(
        "repair_ai_classifier_complete "
        f"considered={result.considered} suggested={result.suggested} output={result.output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
