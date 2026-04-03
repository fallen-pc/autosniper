from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

from scripts.atomic_csv import write_dict_rows_csv_atomic
from shared.condition_normalizer import (
    estimate_component_count,
    load_rules,
    map_categories,
    normalize_text,
    split_defect_lines,
    tokenize,
)
from shared.data_loader import dataset_path


INPUTS = [
    ("sold", Path("CSV_data/restricted/sold_cars_restricted.csv")),
    ("active", Path("CSV_data/restricted/active_vehicle_details_restricted.csv")),
]

OUTPUT_PATH = Path("CSV_data/reports/normalized_conditions.csv")


def _extract_lines(text: str) -> List[str]:
    if not text:
        return []
    lines = split_defect_lines(text)
    return [line for line in lines if line.strip()]


def _emit_rows(rows: Iterable[Dict[str, object]]) -> None:
    write_dict_rows_csv_atomic(
        OUTPUT_PATH,
        fieldnames=[
            "source",
            "url",
            "original_text",
            "normalized_text",
            "tokens",
            "split_index",
            "component_original",
            "component_normalized",
            "category_tags",
            "severity_flag",
            "component_count",
            "confidence_score",
            "rule_trace",
        ],
        rows=rows,
    )


def main() -> None:
    rules = load_rules()
    out_rows: List[Dict[str, object]] = []

    for source, path in INPUTS:
        if not path.exists():
            continue
        df = pd.read_csv(path)
        for _, row in df.iterrows():
            url = row.get("url")
            original = row.get("general_condition", "")
            if original is None or str(original).strip() == "":
                continue
            lines = _extract_lines(str(original))
            for line in lines:
                normalized = normalize_text(line)
                tokens = tokenize(normalized)
                components = split_defect_lines(line)
                if not components:
                    components = [line]
                for idx, component in enumerate(components):
                    component_norm = normalize_text(component)
                    component_tokens = tokenize(component_norm)
                    tags, severity, rule_trace = map_categories(component_norm, component_tokens, rules)
                    component_count = estimate_component_count(component_norm)
                    confidence = 0.99 if tags and tags != ["unknown"] else 0.5
                    out_rows.append(
                        {
                            "source": source,
                            "url": url,
                            "original_text": line,
                            "normalized_text": normalized,
                            "tokens": "|".join(tokens),
                            "split_index": idx,
                            "component_original": component,
                            "component_normalized": component_norm,
                            "category_tags": "|".join(tags),
                            "severity_flag": bool(severity),
                            "component_count": component_count,
                            "confidence_score": confidence,
                            "rule_trace": "|".join(rule_trace),
                        }
                    )

    _emit_rows(out_rows)
    print(f"Wrote {len(out_rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
