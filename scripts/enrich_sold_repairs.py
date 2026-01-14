"""Batch processor that enriches sold listings with repair features and parts-cost estimates."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from shared.repair_features import (
    build_repair_features,
    repair_feature_columns,
    serialize_tags,
)
from shared.parts_cost import estimate_parts_cost
from shared.data_loader import dataset_path

DEFAULT_INPUT = dataset_path("sold_cars.csv")
DEFAULT_OUTPUT = ROOT_DIR / "artifacts" / "training_data" / "sold_cars_repairs_enriched.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich sold listings with repair tagging + parts cost.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Source sold cars CSV.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Destination enriched CSV.")
    return parser.parse_args()


def enrich_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in df.iterrows():
        features = build_repair_features(row.get("general_condition"))
        tags = features.tags
        severity = features.severity
        parts_cost, parts_detail = estimate_parts_cost(tags, severity)
        records.append(
            {
                "general_condition_norm": features.normalized_text,
                "condition_clean": features.clean_text,
                "defects_only": features.defects_only,
                "repair_tags": serialize_tags(tags),
                "repair_severity": severity,
                "decision_condition_only": features.decision_label,
                "estimated_parts_cost_aud": parts_cost,
                "parts_cost_basis": parts_detail,
            }
        )
    enriched = pd.DataFrame(records, index=df.index)
    return pd.concat([df, enriched], axis=1)


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"Input sold dataset not found: {args.input}")
    df = pd.read_csv(args.input, low_memory=False)
    enriched = enrich_dataframe(df)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(args.output, index=False)
    print(f"Wrote {len(enriched):,} rows to {args.output}")


if __name__ == "__main__":
    main()
