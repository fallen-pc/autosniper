# AutoSniper 2

Streamlit dashboard and automation toolkit for monitoring Australian vehicle auctions.

The app reads lightweight CSV datasets, displays live inventory, and lets analysts trigger
AI valuations for interesting cars. Scraping/refresh scripts live alongside the UI so the
whole workflow can be shared on GitHub and hosted on Streamlit Cloud.

---

## Features
- **Streamlit dashboard** (`DASHBOARD.py` & `pages/`) showing status metrics and detailed listings.
- **Data bundle loader** (`shared/data_loader.py`) that optionally pulls CSVs from a remote ZIP.
- **Scrapers** for Grays (production) and Exploratory Autotrader utilities under `scripts/` and `autotrader/`.
- **AI enrichment** via OpenAI for vehicle valuations (`scripts/ai_listing_valuation.py`, Streamlit actions).

---

## Local Development

> **Windows tip:** create the virtual environment with the Windows Python so Streamlit
> resolves to `.\.venv\Scripts\python.exe`. A previous WSL venv (`.venv_wsl/`) is kept only
> for experimentation and is ignored by Git.

1. **Install Python 3.11+** from [python.org](https://www.python.org/downloads/).
2. **Clone the repo** and open PowerShell in the project root.
3. **Create & activate the venv**
   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
4. **Install dependencies**
   ```powershell
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
5. **Configure environment (optional)**
   - Copy `.env.local` to `.streamlit/secrets.toml` or set environment variables directly.
   - For remote data bundles (see below) set `AUTOSNIPER_DATA_URL`.
6. **Run the dashboard**
   ```powershell
   streamlit run DASHBOARD.py
   ```

---

## Commit Hygiene

Enable commit-slicing guardrails once per clone:

```powershell
.\scripts\setup_git_hooks.ps1
```

This activates `.githooks/pre-commit`, which blocks:
- Mixed source + artifact commits
- Oversized staged files
- Oversized commit slices
- Unversioned curve updates
- New legacy-style backup/tmp/copy source filenames

Details: `docs/pr_slicing_and_artifact_hygiene.md`

---

## Governance & CI

Use the governance runner to enforce dataset contracts, curve integrity, and coverage reporting:

```powershell
python scripts/governance_checks.py check
python scripts/governance_checks.py coverage-report
python scripts/governance_checks.py snapshot-curves --note "Describe the curve update"
python scripts/readiness_smoke.py
```

Curve changes are now versioned under `CSV_data/restricted/versions/` and must be paired with
`CHANGELOG.md`. The GitHub Actions workflow in `.github/workflows/governance.yml` runs these
checks in CI and publishes the latest curve coverage report as an artifact/job summary.

More detail: `docs/governance.md`

---

## Curve Operations

The curve-candidate scripts are part of the production operator workflow rather than scratch tools:

```powershell
python scripts/generate_curve_candidates.py
python scripts/process_curve_candidates.py --help
```

- `generate_curve_candidates.py` ranks sold-data tags into `CSV_data/quality/curve_candidates.csv`.
- `process_curve_candidates.py` validates AI curve proposals, updates `CSV_data/restricted/curves.csv`,
  and seeds downstream Autotrader scrape URLs/queue files under `CSV_data/quality/`.
- Any committed `curves.csv` change should be followed by `python scripts/governance_checks.py check`
  and a fresh `snapshot-curves` entry.

---

## Dataset Management

`CSV_data/` holds the working datasets, organized into subfolders:

```
CSV_data/
  scrapers/      # raw + master listings
  ai/            # AI outputs
  restricted/    # VIC Top-12 restricted datasets + curves
  model_audit/   # scored listings + accuracy metrics
  archives/      # historical dumps + legacy archives
  repairs/       # repair estimates
```

If you prefer not to commit CSVs, host a ZIP bundle and point the app to it:

| Variable | Purpose |
| -------- | ------- |
| `AUTOSNIPER_DATA_URL` | HTTPS URL to CSV bundle (ZIP or raw CSV). |
| `AUTOSNIPER_DATA_TOKEN` | Optional Bearer token while downloading. |
| `AUTOSNIPER_DATA_CACHE_MINUTES` | Minutes before re-downloading (default 30). |

The loader extracts into `CSV_data/` on launch for both local and hosted runs.

---

## Autotrader Tools

The experimental Autotrader scrapers live in the `autotrader/` package. Direct access is
rate-limited by Peakhour. If Autotrader returns HTTP 403 you must supply a browser session
cookie or Playwright storage state captured from a real login.

Environment variables:

| Variable | Description |
| -------- | ----------- |
| `AUTOTRADER_COOKIE` | Raw `Cookie:` header copied from a regular browser session (e.g. `PEAKHOUR_VISIT=...; other=value`). |
| `AUTOTRADER_STORAGE_STATE` | Path to a Playwright storage state JSON export to seed cookies/localStorage. |

Usage:

```powershell
# Discover listing URLs (writes autotrader/output/all_listing_links.csv)
python -m autotrader.extract_links --max-pages 5

# Pull detail pages using Playwright
python -m autotrader.scrape_details
```

Without cookies the script exits gracefully and lists the extra configuration required.
The output directory is git-ignored so local runs do not dirty your working tree.

---

## Streamlit Cloud Deployment

1. Push the repository to GitHub (keep `requirements.txt` and the Streamlit files at root).
2. Ensure either:
   - The required CSVs are committed, **or**
   - `AUTOSNIPER_DATA_URL` points to a remote bundle.
3. Create a new app at [share.streamlit.io](https://share.streamlit.io):
   - Connect to the GitHub repo/branch.
   - Set **Main file** to `DASHBOARD.py`.
   - Add secrets / environment variables (`AUTOSNIPER_*`, `OPENAI_API_KEY`, etc.).
4. Deploy – Streamlit Cloud installs dependencies, hydrates the data bundle, and the app
   becomes available at a shareable URL.

To keep the hosted instance in sync, continue committing code changes and updated CSVs (or
refresh the remote ZIP). Redeployments re-run automatically.

---

## Scheduled & Manual Jobs

| Script | Purpose |
| ------ | ------- |
| `scripts/update_bids.py` | Refresh live bids and remaining time for Grays listings. |
| `scripts/update_master.py` | Rebuild master CSVs from scraped data. |
| `scripts/extract_links.py` | Core Grays link discovery. |
| `scripts/extract_vehicle_details.py` | Scrape vehicle details from Grays pages. |
| `scripts/ai_listing_valuation.py` | Batch AI valuations from the command line. |
| `autotrader/extract_links.py` | Experimental Autotrader link crawler (needs cookie/state). |
| `autotrader/scrape_details.py` | Playwright-based Autotrader detail scraper. |

Execute these inside the activated virtual environment so they use the same dependencies.

---

## Troubleshooting

- **`did not find executable at '/usr/bin\python.exe'`** – you are using the old WSL env.
  Reactivate the Windows venv with `.\.venv\Scripts\Activate.ps1`.
- **Autotrader 403 even with Playwright** – copy the browser `Cookie` header to
  `AUTOTRADER_COOKIE` or export a Playwright storage state.
- **Missing CSV warnings** – supply the dataset bundle via `AUTOSNIPER_DATA_URL` or commit
  the files to the repo.
- **Streamlit Cloud build failures** – confirm `requirements.txt` installs on a clean
  environment and secrets are defined in the deployment settings.

---

Maintained as an internal tool; feel free to adapt or prune modules as the workflow evolves.
