# Storage Policy

## Purpose
Classify which files are source-of-truth, which are generated runtime products, and which should not be tracked.

## Principles
- Source code and governed reference data should be easy to review.
- Generated/high-churn operational outputs should not dominate normal commits.
- If a file is reproducible and not manually reviewed, default to untracked.
- If a file encodes business rules, approved reference data, or required governance history, keep it tracked.

## Path policy

| Path | Role | Track? | Regenerable? | Notes |
|------|------|--------|--------------|-------|
| `config/` | Governed configuration/reference data | Yes | Mixed | Treat as reviewed source-of-truth |
| `tests/` | Test source | Yes | N/A | Always tracked |
| `docs/` | Documentation | Yes | N/A | Always tracked |
| `shared/` / future `domain/` | Source code | Yes | N/A | Always tracked |
| `pages/` / future `ui/pages/` | Source code | Yes | N/A | Always tracked |
| `CSV_data/restricted/curves.csv` | Governed pricing asset | Yes | Partially | Must follow versioning/governance rules |
| `CSV_data/restricted/versions/` | Governance history | Yes | No | Required by current governance process |
| `CSV_data/restricted/` other curated maps/configs | Governed datasets | Usually yes | Mixed | Review case by case |
| `CSV_data/quality/curve_candidates.csv` | Generated operator output | Prefer no | Yes | Candidate for untracking if reproducible |
| `CSV_data/scrapers/` | Runtime materialized scrape state | Prefer no / partial | Usually yes | Likely too noisy as a tracked default |
| `CSV_data/ai/` | AI outputs/cache | Case by case | Often yes | Track only if intentional audit history |
| `CSV_data/model_audit/` | Generated audit outputs | Prefer no | Yes | Better as generated outputs/artifacts |
| `CSV_data/archives/` | Historical dumps | Case by case | Often no | Should be intentionally curated if tracked |
| `artifacts/` models + predictions | Generated modeling outputs | Usually no | Often yes | Keep only if intentionally versioned release artifacts |
| `output/` | Generated reports/exports | No | Yes | Should be ignored |
| `logs/` | Logs | No | Yes | Ignored |
| `tmp/` | Temp outputs | No | Yes | Ignored |
| `catboost_info/` | Training run output | No | Yes | Ignored |
| `curves/images/` | Generated visualizations | Usually no | Yes | Track only if explicitly published assets |
| `autotrader_isolated/output/` | Generated scrape output | No | Yes | Ignored |
| `venv/`, `.venv/` | Local environment | No | Yes | Ignored |

## Immediate recommendations
1. Keep governed curve/version assets tracked.
2. Re-evaluate whether `CSV_data/scrapers/`, `CSV_data/ai/`, and `CSV_data/model_audit/` should remain tracked by default.
3. Keep `output/`, `logs/`, `tmp/`, `catboost_info/`, and similar working directories untracked.
4. Treat model binaries/predictions in `artifacts/` as release artifacts only if they are intentionally curated; otherwise untrack them.
5. Avoid committing backup/copy/tmp/final style files anywhere in source directories.

## Current Local Workflow
Until the governed runtime dataset is moved to a separate backup/release
channel, use `scripts/git_runtime_quiet.ps1` to hide normal local CSV churn from
source-oriented `git status` output. Keep that local quieting separate from
intentional data commits: unquiet first, stage explicit data paths, run
governance checks, and commit artifacts separately from source changes.

## Decision rule for new files
Before tracking a new data/artifact file, answer:
1. Is it a source-of-truth input or approved governance history?
2. Is it manually reviewed?
3. Would losing it break reproducibility or auditability?
4. Can it be regenerated cheaply and reliably?

If the answer is “generated and reproducible,” default to untracked.
