# Findings

This file is now a compatibility summary.

## Main Finding

AutoSniper needed enforced project memory, not just "files an agent should remember to read."

## Current Truth

- authoritative memory now lives under `project_memory/`
- machine-readable rules are generated from code-backed sources
- durable decisions live in `project_memory/03_decisions/`
- current operational truth lives in `project_memory/02_state/`

## Use Instead

- `project_memory/memory_manifest.yaml`
- `project_memory/02_state/`
- `project_memory/03_decisions/`
- `project_memory/04_references/legacy_memory_bootstrap.md`
