## Purpose

This file provides focused, actionable guidance for AI coding agents working on AutoSniper
so they can be productive immediately. It summarizes the architecture, dev workflows,
common conventions, and important integration points discovered in the repo.

## Big picture

- Single-process Streamlit UI: entrypoint is `DASHBOARD.py` (root). The UI consumes
  lightweight CSVs from `CSV_data/` produced by scrapers and scheduled scripts.
- Shared utilities live under `shared/` (notably `shared/data_loader.py` and
  `shared/styling.py`). Use `dataset_path(...)` and `ensure_datasets_available(...)` to
  locate and validate datasets before operating on them.
- Scrapers & jobs are under `scripts/` and an experimental `autotrader/` package. These
  produce CSV outputs (some in gitignored `autotrader/output/`) which the dashboard
  reads as authoritative sources.

## Developer workflows (commands & caveats)

- Local venv (Windows):
  - py -3 -m venv .venv
  - .\.venv\Scripts\Activate.ps1
  - python -m pip install -r requirements.txt
- Run Streamlit dashboard: `streamlit run DASHBOARD.py` (Main file for Streamlit Cloud)
- Data bundle: `AUTOSNIPER_DATA_URL` (zip or raw CSVs) — `shared/data_loader.py` extracts
  into `CSV_data/`. Use `AUTOSNIPER_DATA_TOKEN` for bearer auth and
  `AUTOSNIPER_DATA_CACHE_MINUTES` to control re-downloads.
- Autotrader tooling (experimental): prefer module execution and Playwright state.
  - python -m autotrader.extract_links --max-pages 5
  - python -m autotrader.scrape_details
  - Requires `AUTOTRADER_COOKIE` (raw Cookie header) or `AUTOTRADER_STORAGE_STATE` (Playwright JSON).

## Project-specific conventions & patterns

- Dataset-first design: many components assume CSVs exist with canonical filenames
  (see README allowlist like `vehicle_static_details.csv`). Always call
  `ensure_datasets_available([...])` before reading CSVs; the dashboard uses this guard.
- Use module-run entrypoints (`python -m package.module`) for scripts rather than
  executing files by path. This preserves package imports and relative imports.
- Async Playwright scrapers: `autotrader.scrape_details` and some scripts use async
  I/O. Keep long-running scrapers outside the Streamlit process.
- Type hints use modern Python 3.11 syntax (e.g. `list[str]`, `tuple[str,str]`) —
  follow this style when editing or adding functions.

## Integration points & secrets

- OpenAI: `scripts/ai_listing_valuation.py` expects `OPENAI_API_KEY` (or Streamlit
  secrets). The dashboard can trigger AI enrichment flows; keep calls idempotent.
- Playwright / Autotrader: set `AUTOTRADER_COOKIE` or `AUTOTRADER_STORAGE_STATE` to
  avoid HTTP 403. Outputs are written to `autotrader/output/` which is gitignored.
- Streamlit Cloud: set env vars and/or commit key CSVs. Main file must be set to
  `DASHBOARD.py` in the deployment settings.

## Where to look for examples (quick links)

- Dashboard dataset loading & guards: `DASHBOARD.py` (root)
- Shared loader: `shared/data_loader.py` (use `dataset_path` + `ensure_datasets_available`)
- AI valuation: `scripts/ai_listing_valuation.py`
- Scheduled scrapers: `scripts/update_bids.py`, `scripts/update_master.py`, `scripts/extract_links.py`
- Experimental Autotrader: `autotrader/` (README and `extract_links.py`, `scrape_details.py`)

## Constraints & safe edits

- Many CSVs are considered canonical; avoid renaming those files unless you update
  `shared/data_loader.py` and references in `DASHBOARD.py` and scripts.
- Do not run Playwright scrapers on CI without secrets; they require session state.
- Small docs or helper tests are welcome; do not change Streamlit layout or secrets
  handling without verifying local run with `streamlit run DASHBOARD.py`.

## Merge guidance

- If a prior `.github/copilot-instructions.md` exists, merge by preserving specific
  env var names, dataset filenames, and the commands under "Local Development".

---
If anything here looks incomplete or you want more examples (e.g. the exact
column names expected in `vehicle_static_details.csv`), tell me which area to expand
and I will update this file.
