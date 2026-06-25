from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.repair_pricing import assess_repairs, repair_decision_label, repair_fragments_to_records


DEFAULT_INPUTS = [
    "CSV_data/scrapers/active_vehicle_details.csv",
    "CSV_data/scrapers/vehicle_static_details.csv",
    "CSV_data/scrapers/sold_cars.csv",
    "CSV_data/scrapers/referred_cars.csv",
    "CSV_data/scrapers/sold_price_pending.csv",
    "CSV_data/restricted/active_vehicle_details_restricted.csv",
    "CSV_data/restricted/sold_cars_restricted.csv",
    "CSV_data/archives/sold_cars_rescraped.csv",
    "CSV_data/archives/sold_cars_historical.csv",
]

DEFAULT_OUTPUT = Path("CSV_data/reports/grays_condition_repair_lines.csv")
DEFAULT_FRAGMENTS_OUTPUT = Path("CSV_data/reports/grays_condition_repair_fragments.csv")
DEFAULT_SUMMARY_OUTPUT = Path("CSV_data/reports/grays_condition_repair_summary.json")

FEATURE_LINE_PATTERN = re.compile(
    r"\b("
    r"air conditioning|auto control|bluetooth|bull bar|cd player|central locking|climate control|"
    r"cruise control|driver airbag|electric seat|electric windows|mp3 capability|"
    r"multi function steering wheel|park distance control|power steering|reversing camera|"
    r"side steps|tow bar|trip computer"
    r")\b",
    re.IGNORECASE,
)

FEATURE_LINE_REPAIR_WORD_PATTERN = re.compile(
    r"\b("
    r"broken|crack|cracked|damage|damaged|fault|faulty|inoperative|not working|"
    r"requires attention|torn|worn"
    r")\b",
    re.IGNORECASE,
)

EMBEDDED_FEATURES_PATTERN = re.compile(r"\bfeatures\s*:", re.IGNORECASE)


def normalize_key(text: object) -> str:
    cleaned = str(text or "").lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def safe_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def vehicle_title(row: pd.Series) -> str:
    parts = [
        safe_text(row.get("year")).split(".")[0],
        safe_text(row.get("make")),
        safe_text(row.get("model")),
        safe_text(row.get("variant")),
    ]
    return " ".join(part for part in parts if part) or "Unknown vehicle"


def is_feature_only_line(text: object) -> bool:
    line = safe_text(text)
    if not line:
        return False
    if FEATURE_LINE_REPAIR_WORD_PATTERN.search(line):
        return False
    return bool(FEATURE_LINE_PATTERN.search(line))


def filter_feature_only_condition_text(text: object) -> tuple[str, list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        features_match = EMBEDDED_FEATURES_PATTERN.search(line)
        if features_match:
            feature_tail = line[features_match.start() :].strip()
            line = line[: features_match.start()].strip(" .;:-")
            if feature_tail:
                dropped.append(feature_tail)
            if not line:
                continue
        if is_feature_only_line(line):
            dropped.append(line)
            continue
        kept.append(line)
    return "\n".join(kept), dropped


def iter_condition_rows(input_paths: Iterable[Path]) -> Iterable[dict[str, object]]:
    seen: set[tuple[str, str]] = set()
    for path in input_paths:
        if not path.exists():
            continue
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        if "general_condition" not in df.columns:
            continue
        for _, row in df.iterrows():
            raw_condition_text = safe_text(row.get("general_condition"))
            condition_text, dropped_feature_lines = filter_feature_only_condition_text(raw_condition_text)
            if not condition_text:
                continue
            url = safe_text(row.get("url"))
            row_key = (url, normalize_key(condition_text))
            if row_key in seen:
                continue
            seen.add(row_key)
            yield {
                "source_file": str(path),
                "url": url,
                "vehicle": vehicle_title(row),
                "year": safe_text(row.get("year")).split(".")[0],
                "make": safe_text(row.get("make")),
                "model": safe_text(row.get("model")),
                "variant": safe_text(row.get("variant")),
                "canonical_tag": safe_text(row.get("canonical_tag")),
                "general_condition": condition_text,
                "raw_general_condition": raw_condition_text,
                "dropped_feature_lines": " | ".join(dropped_feature_lines),
            }


def build_fragment_rows(condition_rows: Iterable[dict[str, object]]) -> tuple[list[dict[str, object]], int]:
    fragment_rows: list[dict[str, object]] = []
    assessment_cache: dict[str, tuple[str, list[dict[str, object]]]] = {}
    dropped_feature_fragment_count = 0
    for condition_row in condition_rows:
        condition_key = normalize_key(condition_row["general_condition"])
        if condition_key not in assessment_cache:
            assessment = assess_repairs(condition_row["general_condition"])
            assessment_cache[condition_key] = (
                repair_decision_label(assessment),
                repair_fragments_to_records(assessment),
            )
        decision, records = assessment_cache[condition_key]
        dropped_feature_fragments: list[str] = []
        for index, record in enumerate(records, start=1):
            original_text = safe_text(record.get("original_text"))
            if is_feature_only_line(original_text):
                dropped_feature_fragments.append(original_text)
                dropped_feature_fragment_count += 1
                continue
            repair_key = safe_text(record.get("repair_key")) or normalize_key(original_text)
            if not original_text or not repair_key:
                continue
            fragment_rows.append(
                {
                    **condition_row,
                    "dropped_feature_fragments": " | ".join(dropped_feature_fragments),
                    "fragment_index": index,
                    "repair_item": original_text,
                    "repair_key": repair_key,
                    "status": safe_text(record.get("status")) or "unclassified",
                    "category": safe_text(record.get("category")) or "unclassified",
                    "canonical_defects": safe_text(record.get("canonical_defects")),
                    "pills": safe_text(record.get("pills")),
                    "cost_estimate": record.get("cost_estimate", 0),
                    "hard_avoid_reason": safe_text(record.get("hard_avoid_reason")),
                    "reasons": safe_text(record.get("reasons")),
                    "repair_decision": decision,
                }
            )
    return fragment_rows, dropped_feature_fragment_count


def join_limited(values: Iterable[str], limit: int = 8) -> str:
    cleaned = []
    seen: set[str] = set()
    for value in values:
        text = safe_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return " | ".join(cleaned)


def most_common(values: Iterable[str], default: str = "") -> str:
    counter = Counter(safe_text(value) for value in values if safe_text(value))
    if not counter:
        return default
    return counter.most_common(1)[0][0]


def build_deduped_rows(fragment_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in fragment_rows:
        grouped[str(row["repair_key"])].append(row)

    deduped: list[dict[str, object]] = []
    for repair_key, rows in grouped.items():
        categories = [safe_text(row.get("category")) or "unclassified" for row in rows]
        statuses = [safe_text(row.get("status")) or "unclassified" for row in rows]
        canonical_defects = [safe_text(row.get("canonical_defects")) for row in rows]
        pills = [safe_text(row.get("pills")) for row in rows]
        costs = pd.to_numeric(pd.Series([row.get("cost_estimate", 0) for row in rows]), errors="coerce").fillna(0)
        urls = {safe_text(row.get("url")) for row in rows if safe_text(row.get("url"))}
        condition_notes = {safe_text(row.get("general_condition")) for row in rows if safe_text(row.get("general_condition"))}
        deduped.append(
            {
                "category": most_common(categories, "unclassified"),
                "status": most_common(statuses, "unclassified"),
                "repair_key": repair_key,
                "repair_item": most_common([row.get("repair_item") for row in rows], repair_key),
                "occurrences": len(rows),
                "listing_count": len(urls) if urls else len(condition_notes),
                "canonical_defects": join_limited(canonical_defects),
                "pills": join_limited(pills),
                "max_cost_estimate": float(costs.max()) if not costs.empty else 0.0,
                "avg_cost_estimate": float(costs.mean()) if not costs.empty else 0.0,
                "hard_avoid_reasons": join_limited(row.get("hard_avoid_reason", "") for row in rows),
                "source_files": join_limited(row.get("source_file", "") for row in rows),
                "example_vehicles": join_limited((row.get("vehicle", "") for row in rows), limit=5),
                "example_urls": join_limited((row.get("url", "") for row in rows), limit=5),
                "example_condition_notes": join_limited(
                    (row.get("general_condition", "") for row in rows),
                    limit=3,
                ),
            }
        )
    return deduped


def write_outputs(
    fragment_rows: list[dict[str, object]],
    condition_rows: list[dict[str, object]],
    dropped_feature_fragment_count: int,
    output_path: Path,
    fragments_output_path: Path,
    summary_output_path: Path,
) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fragments_output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_output_path.parent.mkdir(parents=True, exist_ok=True)

    fragments_df = pd.DataFrame(fragment_rows)
    if not fragments_df.empty:
        fragments_df.sort_values(
            by=["category", "status", "repair_key", "source_file", "vehicle"],
            ascending=[True, True, True, True, True],
            inplace=True,
        )
    fragments_df.to_csv(fragments_output_path, index=False)

    deduped_df = pd.DataFrame(build_deduped_rows(fragment_rows))
    if not deduped_df.empty:
        deduped_df.sort_values(
            by=["category", "status", "occurrences", "repair_key"],
            ascending=[True, True, False, True],
            inplace=True,
        )
    deduped_df.to_csv(output_path, index=False)

    summary = {
        "condition_rows_after_feature_filter": len(condition_rows),
        "dropped_feature_lines": int(
            sum(
                len([part for part in safe_text(row.get("dropped_feature_lines")).split(" | ") if part])
                for row in condition_rows
            )
        ),
        "dropped_feature_fragments": int(dropped_feature_fragment_count),
        "condition_notes": int(fragments_df[["source_file", "url", "general_condition"]].drop_duplicates().shape[0])
        if not fragments_df.empty
        else 0,
        "fragment_occurrences": int(fragments_df.shape[0]),
        "deduped_repair_lines": int(deduped_df.shape[0]),
        "matched_lines": int((fragments_df.get("status", pd.Series(dtype=str)) == "matched").sum())
        if not fragments_df.empty
        else 0,
        "unclassified_lines": int((fragments_df.get("status", pd.Series(dtype=str)) == "unclassified").sum())
        if not fragments_df.empty
        else 0,
        "category_counts": deduped_df["category"].value_counts().to_dict() if not deduped_df.empty else {},
        "status_counts": deduped_df["status"].value_counts().to_dict() if not deduped_df.empty else {},
        "outputs": {
            "deduped": str(output_path),
            "fragments": str(fragments_output_path),
            "summary": str(summary_output_path),
        },
    }
    summary_output_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract Grays condition notes, split them with the shared repair parser, and output categorized repair lines."
    )
    parser.add_argument(
        "--input",
        action="append",
        dest="inputs",
        help="Input CSV path. Can be supplied multiple times. Defaults to current Grays active/sold/referred datasets.",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Deduped repair-line CSV output path.")
    parser.add_argument(
        "--fragments-output",
        default=str(DEFAULT_FRAGMENTS_OUTPUT),
        help="Occurrence-level repair-fragment CSV output path.",
    )
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY_OUTPUT), help="Summary JSON output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_paths = [Path(path) for path in (args.inputs or DEFAULT_INPUTS)]
    condition_rows = list(iter_condition_rows(input_paths))
    fragment_rows, dropped_feature_fragment_count = build_fragment_rows(condition_rows)
    summary = write_outputs(
        fragment_rows,
        condition_rows,
        dropped_feature_fragment_count,
        Path(args.output),
        Path(args.fragments_output),
        Path(args.summary_output),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
