from __future__ import annotations

import argparse
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.repair_review import normalized_review_key, safe_text


DEFAULT_QUEUE_PATH = Path("CSV_data/reports/repair_review_live_queue.csv")
DEFAULT_EXTERNAL_PATH = Path("output/external_auction_scrape/daily/external_auction_listings_all.csv")
REQUIRED_QUEUE_COLUMNS = {"repair_key", "source_file", "example_urls"}
REQUIRED_EXTERNAL_COLUMNS = {"source", "url", "scrape_status", "general_condition"}


@dataclass(frozen=True)
class RebuildSummary:
    source: str
    queue_rows_before: int
    queue_rows_after: int
    parsed_urls: int
    candidate_rows: int
    removed_rows: int
    retained_candidate_rows: int


def _require_columns(df: pd.DataFrame, required: set[str], *, label: str) -> None:
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")


def _current_condition_evidence(external_df: pd.DataFrame, *, source: str) -> dict[str, str]:
    _require_columns(external_df, REQUIRED_EXTERNAL_COLUMNS, label="External listing data")
    scoped = external_df[
        external_df["source"].astype(str).str.strip().str.lower().eq(source.lower())
        & external_df["scrape_status"].astype(str).str.strip().str.lower().eq("parsed")
    ]
    evidence: dict[str, list[str]] = {}
    for _, row in scoped.iterrows():
        url = safe_text(row.get("url"))
        if not url:
            continue
        evidence.setdefault(url, []).append(safe_text(row.get("general_condition")))
    return {
        url: normalized_review_key("\n".join(part for part in condition_parts if part))
        for url, condition_parts in evidence.items()
    }


def rebuild_external_repair_queue(
    queue_df: pd.DataFrame,
    external_df: pd.DataFrame,
    *,
    source: str = "pickles",
) -> tuple[pd.DataFrame, pd.DataFrame, RebuildSummary]:
    _require_columns(queue_df, REQUIRED_QUEUE_COLUMNS, label="Repair review queue")
    current_evidence = _current_condition_evidence(external_df, source=source)
    parsed_urls = set(current_evidence)

    source_files = queue_df["source_file"].astype(str).str.strip().str.upper()
    urls = queue_df["example_urls"].astype(str).str.strip()
    candidate_mask = source_files.eq("ACTIVE_MONITOR") & urls.isin(parsed_urls)
    remove_mask = pd.Series(False, index=queue_df.index)
    for index, row in queue_df[candidate_mask].iterrows():
        repair_key = normalized_review_key(row.get("repair_key"))
        if not repair_key:
            continue
        condition_evidence = current_evidence[safe_text(row.get("example_urls"))]
        if repair_key not in condition_evidence:
            remove_mask.loc[index] = True

    cleaned = queue_df.loc[~remove_mask].copy()
    removed = queue_df.loc[remove_mask].copy()
    candidate_rows = int(candidate_mask.sum())
    removed_rows = int(remove_mask.sum())
    summary = RebuildSummary(
        source=source,
        queue_rows_before=len(queue_df),
        queue_rows_after=len(cleaned),
        parsed_urls=len(parsed_urls),
        candidate_rows=candidate_rows,
        removed_rows=removed_rows,
        retained_candidate_rows=candidate_rows - removed_rows,
    )
    return cleaned, removed, summary


def write_rebuilt_queue(
    *,
    queue_path: Path,
    cleaned_df: pd.DataFrame,
    created_at: datetime | None = None,
) -> Path:
    queue_path = queue_path.resolve()
    if not queue_path.is_file():
        raise FileNotFoundError(f"Repair review queue does not exist: {queue_path}")
    timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    backup_path = queue_path.with_name(
        f"{queue_path.stem}.pre_external_rebuild_{timestamp.strftime('%Y%m%dT%H%M%SZ')}{queue_path.suffix}"
    )
    if backup_path.exists():
        raise FileExistsError(f"Queue backup already exists: {backup_path}")
    shutil.copy2(queue_path, backup_path)
    write_dataframe_csv_atomic(cleaned_df, queue_path, index=False)
    return backup_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prune stale ACTIVE_MONITOR repair rows using successfully parsed external condition evidence."
    )
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE_PATH)
    parser.add_argument("--external-listings", type=Path, default=DEFAULT_EXTERNAL_PATH)
    parser.add_argument("--source", default="pickles")
    parser.add_argument("--apply", action="store_true", help="Write the rebuilt queue after creating a sibling backup.")
    parser.add_argument("--removed-report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    queue_df = pd.read_csv(args.queue, low_memory=False).fillna("")
    external_df = pd.read_csv(args.external_listings, low_memory=False).fillna("")
    cleaned_df, removed_df, summary = rebuild_external_repair_queue(
        queue_df,
        external_df,
        source=args.source,
    )
    print(pd.Series(asdict(summary)).to_string())
    if not removed_df.empty:
        sample_columns = [column for column in ("repair_key", "source_file", "example_urls") if column in removed_df]
        print("Removed-row sample:")
        print(removed_df[sample_columns].head(20).to_string(index=False))
    if args.removed_report:
        write_dataframe_csv_atomic(removed_df, args.removed_report, index=False)
        print(f"Removed-row report: {args.removed_report}")
    if not args.apply:
        print("Dry run only; queue was not changed.")
        return
    if removed_df.empty:
        print("No stale rows found; queue was not changed.")
        return
    backup_path = write_rebuilt_queue(queue_path=args.queue, cleaned_df=cleaned_df)
    print(f"Queue backup: {backup_path}")
    print(f"Rebuilt queue: {args.queue}")


if __name__ == "__main__":
    main()
