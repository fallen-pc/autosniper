"""End-to-end rebuild of the auction price correction CatBoost model.

Runs the three pipeline steps in sequence and writes all outputs to a
versioned directory so nothing overwrites the current production models
until you're ready to promote.

Usage (from repo root):
    python -m scripts.rebuild_auction_model
    python -m scripts.rebuild_auction_model --out-dir artifacts/rebuild_test --skip-enrich
    python -m scripts.rebuild_auction_model --clip-low 0.40 --clip-high 2.0 --min-comps 3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from shared.data_loader import dataset_path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SOLD_SOURCE = dataset_path("sold_cars.csv")
DEFAULT_SOLD_SOURCE_RESTRICTED = dataset_path("sold_cars_restricted.csv")
DEFAULT_GROUP_MAP = dataset_path("restricted_group_map.csv")
DEFAULT_SNAPSHOTS = dataset_path("active_snapshots.csv")
DEFAULT_SNAPSHOT_ARCHIVE = dataset_path("archives/active_snapshots")

# Clip range: 0.40–2.0 keeps outlier-tolerant while discarding cases where
# comps_p50 was more than 2.5× off (typically garbage baselines).
DEFAULT_CLIP_LOW = 0.40
DEFAULT_CLIP_HIGH = 2.0

# Raise the upper quantile slightly above 0.9 to compensate for the
# under-coverage observed in the March 2026 training run (81.8% actual
# coverage vs 90% target).
DEFAULT_Q90_ALPHA = 0.92

# Drop rows where the comps engine had fewer than this many comparables —
# a sparse comps baseline makes the ratio target noisy.
DEFAULT_MIN_COMPS = 3

# Columns that carry target-leakage or are pure identifiers — never features.
# comps_median / comps_median_year / comps_count_group / comps_count_year are
# the raw groupby stats used to construct comps_p50; drop them so the model
# cannot peek at group-level stats beyond the baseline.
ALWAYS_DROP = [
    "sale_price",
    "sale_price_value",
    "price",
    "price_numeric",
    "price_text",
    "comps_error",
    "auction_ratio",
    "url",
    "vin",
    "rego_no",
    "parts_cost_basis",
    "general_condition",
    "general_condition_norm",
    "condition_clean",
    "defects_only",
    # aligned-pipeline groupby stats (rolled into comps_p50 already)
    "comps_median",
    "comps_median_year",
    "comps_count_group",
    "comps_count_year",
    "comps_p90",   # legacy CompsEngine column (not present in aligned)
    "comps_confidence",  # legacy CompsEngine column
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], label: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"\nERROR: {label} exited with code {result.returncode}. Aborting.")
        sys.exit(result.returncode)


def _write_validation_report(metrics_path: Path, predictions_path: Path, out_path: Path) -> None:
    with open(metrics_path, encoding="utf-8") as fh:
        metrics = json.load(fh)

    preds = pd.read_csv(predictions_path)

    q50_mae = metrics["price_metrics_q50"]["mae"]
    q50_rmse = metrics["price_metrics_q50"]["rmse"]
    q50_wape = metrics["price_metrics_q50"]["wape"]
    raw_coverage = metrics.get("coverage_upper_raw", metrics.get("coverage_upper", float("nan")))
    calibrated_coverage = metrics.get("coverage_upper_calibrated", metrics.get("coverage_p90", float("nan")))
    calibration_multiplier = metrics.get("calibration_multiplier", 1.0)
    q90_alpha = metrics.get("q90_alpha", 0.9)
    rows_train = metrics["rows_train"]
    rows_valid = metrics["rows_valid"]
    clip_low = metrics["clip_low"]
    clip_high = metrics["clip_high"]
    median_ratio = metrics.get("median_ratio_valid", float("nan"))
    n_features = len(metrics.get("features", []))

    # Error percentile breakdown
    abs_errors = preds["abs_error_q50"].dropna()
    p50_err = float(np.percentile(abs_errors, 50))
    p75_err = float(np.percentile(abs_errors, 75))
    p90_err = float(np.percentile(abs_errors, 90))
    p99_err = float(np.percentile(abs_errors, 99))

    # Coverage at multiple thresholds
    within_500 = float((abs_errors <= 500).mean())
    within_1000 = float((abs_errors <= 1000).mean())
    within_2000 = float((abs_errors <= 2000).mean())

    # Ratio distribution on validation set
    actual_ratios = preds["actual_ratio"].dropna()
    ratio_p10 = float(np.percentile(actual_ratios, 10))
    ratio_p50 = float(np.percentile(actual_ratios, 50))
    ratio_p90 = float(np.percentile(actual_ratios, 90))

    # Directional accuracy: did q50 predict the right side of the actual?
    correct_direction = float(
        ((preds["pred_price_q50"] >= preds["actual_price"]) == (preds["pred_ratio_q50"] >= preds["actual_ratio"])).mean()
    )

    # Upper model calibration: what fraction of actuals fall below q90 prediction?
    upper_coverage_actual = float((preds["actual_price"] <= preds["pred_price_q90"]).mean())

    report = textwrap.dedent(f"""\
        # Auction Price Correction Model — Validation Report
        Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}

        ## Training Configuration
        | Parameter | Value |
        |---|---|
        | Training rows | {rows_train:,} |
        | Validation rows (holdout) | {rows_valid:,} |
        | Feature count | {n_features} |
        | Clip range | {clip_low} – {clip_high} |
        | Upper model alpha | {q90_alpha} |
        | Median actual ratio (valid) | {median_ratio:.3f} |

        ## Q50 Model — Price Prediction Accuracy
        | Metric | Value |
        |---|---|
        | MAE | ${q50_mae:,.0f} |
        | RMSE | ${q50_rmse:,.0f} |
        | WAPE | {q50_wape:.1%} |

        ## Q50 Model — Error Distribution
        | Percentile | Absolute Error |
        |---|---|
        | p50 (median error) | ${p50_err:,.0f} |
        | p75 | ${p75_err:,.0f} |
        | p90 | ${p90_err:,.0f} |
        | p99 | ${p99_err:,.0f} |

        ## Q50 Model — Coverage by Tolerance
        | Tolerance | % of predictions within |
        |---|---|
        | ±$500 | {within_500:.1%} |
        | ±$1,000 | {within_1000:.1%} |
        | ±$2,000 | {within_2000:.1%} |

        ## Upper Model (alpha={q90_alpha}) — Calibration
        | Metric | Value | Target |
        |---|---|---|
        | Raw coverage (no calibration) | {raw_coverage:.1%} | |
        | Calibration multiplier | {calibration_multiplier:.4f} | 1.0 ideally |
        | Calibrated coverage | {calibrated_coverage:.1%} | >={q90_alpha:.0%} |
        | Status | {"OK" if calibrated_coverage >= q90_alpha else "FAIL - still under-covers after calibration, check for extreme ratio outliers in validation set"} | |

        The calibration multiplier is applied to q90 price predictions at inference time.
        A multiplier far from 1.0 (e.g. > 1.15 or < 0.90) means the base model is
        systematically biased - investigate comps engine quality for the affected vehicles.

        ## Validation Set — Actual Ratio Distribution
        (ratio = actual_auction_price / comps_p50 baseline)
        | Percentile | Ratio |
        |---|---|
        | p10 | {ratio_p10:.3f} |
        | p50 | {ratio_p50:.3f} |
        | p90 | {ratio_p90:.3f} |

        ## Next Steps
        - If MAE > $1,500 or WAPE > 20%: review comps engine quality or add more training data.
        - If upper model coverage < alpha target: rerun with --q90-alpha 0.94 or 0.95.
        - If p99 error > $10,000: check for rows with very low comps_count leaking through
          (rerun with --min-comps 5).
        - When satisfied: copy .cbm files and feature_names.json to artifacts/ to promote.
    """)

    out_path.write_text(report, encoding="utf-8")
    print(f"\nValidation report written to: {out_path}")
    print(report)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild auction price correction models end-to-end."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to artifacts/rebuild_YYYYMMDD.",
    )
    parser.add_argument(
        "--aligned",
        action="store_true",
        help=(
            "Use the aligned pipeline (sold_cars_restricted.csv + groupby-median baseline) "
            "instead of the legacy CompsEngine pipeline. Recommended."
        ),
    )
    parser.add_argument(
        "--sold-source",
        type=Path,
        default=None,
        help="Override source CSV path (default: sold_cars_restricted.csv in aligned mode, sold_cars.csv otherwise).",
    )
    parser.add_argument(
        "--group-map",
        type=Path,
        default=DEFAULT_GROUP_MAP,
        help="Path to restricted_group_map.csv (aligned mode only).",
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Skip repair enrichment step (legacy pipeline only; aligned pipeline does enrichment inline).",
    )
    parser.add_argument(
        "--skip-training-table",
        action="store_true",
        help="Skip training table build step (reuse existing training table CSV).",
    )
    parser.add_argument(
        "--clip-low",
        type=float,
        default=DEFAULT_CLIP_LOW,
        help=f"Lower ratio clip (default {DEFAULT_CLIP_LOW}).",
    )
    parser.add_argument(
        "--clip-high",
        type=float,
        default=DEFAULT_CLIP_HIGH,
        help=f"Upper ratio clip (default {DEFAULT_CLIP_HIGH}).",
    )
    parser.add_argument(
        "--q90-alpha",
        type=float,
        default=DEFAULT_Q90_ALPHA,
        help=f"Upper quantile alpha (default {DEFAULT_Q90_ALPHA}).",
    )
    parser.add_argument(
        "--min-comps",
        type=int,
        default=DEFAULT_MIN_COMPS,
        help=f"Min comps_count to include a row in training (default {DEFAULT_MIN_COMPS}).",
    )
    parser.add_argument(
        "--validation-days",
        type=int,
        default=60,
        help="Holdout window in days (default 60).",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=2500,
        help="Max CatBoost iterations (default 2500).",
    )
    parser.add_argument(
        "--val-frac",
        type=float,
        default=0.20,
        help="Random validation fraction (default 0.20). Set to 0 to use time-based split instead.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    dated_tag = datetime.now().strftime("%Y%m%d")
    out_dir: Path = args.out_dir or (ROOT_DIR / "artifacts" / f"rebuild_{dated_tag}")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {out_dir}")

    enriched_path = out_dir / "sold_cars_repairs_enriched.csv"
    training_table_path = out_dir / "sold_training_table.csv"
    model_q50_path = out_dir / "auction_ratio_q50.cbm"
    model_q90_path = out_dir / "auction_ratio_q90.cbm"
    metrics_path = out_dir / "correction_model_metrics.json"
    predictions_path = out_dir / "correction_model_predictions.csv"
    features_path = out_dir / "feature_names.json"
    report_path = out_dir / "validation_report.md"

    # Resolve sold source default based on mode.
    # Aligned mode uses sold_cars_restricted.csv — it has far better curve_tag coverage
    # than sold_cars.csv (which covers all states/models but mostly outside our curve system).
    if args.sold_source is None:
        args.sold_source = DEFAULT_SOLD_SOURCE_RESTRICTED if args.aligned else DEFAULT_SOLD_SOURCE

    mode_label = "ALIGNED (restricted+groupby-median)" if args.aligned else "LEGACY (CompsEngine)"
    print(f"Pipeline mode: {mode_label}")

    # ------------------------------------------------------------------
    # Steps 1+2: Build training table
    # ------------------------------------------------------------------
    if args.skip_training_table:
        print(f"\nSkipping training table build — expecting {training_table_path}")
        if not training_table_path.exists():
            print(f"ERROR: --skip-training-table set but table not found: {training_table_path}")
            sys.exit(1)
    elif args.aligned:
        # Aligned pipeline: one script handles load + filter + baseline + enrich + features
        _run(
            [
                sys.executable, "-m", "scripts.build_aligned_training_table",
                "--training-source", str(args.sold_source),
                "--baseline-source", str(DEFAULT_SOLD_SOURCE_RESTRICTED),
                "--output", str(training_table_path),
                "--snapshots-path", str(DEFAULT_SNAPSHOTS),
                "--snapshot-archive-dir", str(DEFAULT_SNAPSHOT_ARCHIVE),
                "--min-comps-count", str(args.min_comps),
            ],
            "Steps 1+2/3: Build aligned training table (all-states rows + restricted baseline)",
        )
    else:
        # Legacy pipeline: enrich then prepare
        if args.skip_enrich:
            print(f"\nSkipping enrichment — expecting {enriched_path}")
            if not enriched_path.exists():
                print(f"ERROR: --skip-enrich set but enriched file not found: {enriched_path}")
                sys.exit(1)
        else:
            _run(
                [
                    sys.executable, "-m", "scripts.enrich_sold_repairs",
                    "--input", str(args.sold_source),
                    "--output", str(enriched_path),
                ],
                "Step 1/3: Repair enrichment (legacy)",
            )

        _run(
            [
                sys.executable, "-m", "scripts.prepare_sold_training_data",
                "--input", str(enriched_path),
                "--output", str(training_table_path),
                "--snapshots-path", str(DEFAULT_SNAPSHOTS),
                "--snapshot-archive-dir", str(DEFAULT_SNAPSHOT_ARCHIVE),
            ],
            "Step 2/3: Build training table (CompsEngine + temporal features, legacy)",
        )

    # ------------------------------------------------------------------
    # Step 3: Train models
    # ------------------------------------------------------------------
    drop_cols = ",".join(ALWAYS_DROP)
    _run(
        [
            sys.executable, "-m", "scripts.train_auction_price_correction",
            "--train-data", str(training_table_path),
            "--out-dir", str(out_dir),
            "--model-q50-out", str(model_q50_path),
            "--model-q90-out", str(model_q90_path),
            "--metrics-out", str(metrics_path),
            "--predictions-out", str(predictions_path),
            "--features-out", str(features_path),
            "--clip-low", str(args.clip_low),
            "--clip-high", str(args.clip_high),
            "--q90-alpha", str(args.q90_alpha),
            "--min-comps", str(args.min_comps),
            "--validation-days", str(args.validation_days),
            "--val-frac", str(args.val_frac),
            "--iterations", str(args.iterations),
            "--drop-cols", drop_cols,
        ],
        "Step 3/3: Train CatBoost models",
    )

    # ------------------------------------------------------------------
    # Validation report
    # ------------------------------------------------------------------
    _write_validation_report(metrics_path, predictions_path, report_path)

    print(f"\n{'='*60}")
    print("  Rebuild complete.")
    print(f"  Models:  {model_q50_path.name}, {model_q90_path.name}")
    print(f"  Features: {features_path.name}")
    print(f"  Report:   {report_path.name}")
    print(f"  All outputs in: {out_dir}")
    print()
    print("  To promote to production when satisfied:")
    print(f"    copy {out_dir}\\auction_ratio_q50.cbm artifacts\\")
    print(f"    copy {out_dir}\\auction_ratio_q90.cbm artifacts\\")
    print(f"    copy {out_dir}\\feature_names.json artifacts\\")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
