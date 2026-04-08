# Open Issues

- Profit-related terms and calculations may still drift across code and UI surfaces.
- Curve Builder V2 expansion blockers are not fully mapped yet; likely candidates include tag resolution, supported-universe constraints, governance thresholds, and workflow friction.
- Scraper and extractor surfaces remain high sensitivity and should not be reopened casually.
- The external Codex/OpenClaw launcher must call `python scripts/project_memory.py build-context ...` before starting an AI task, because the repo cannot force that step by itself.
