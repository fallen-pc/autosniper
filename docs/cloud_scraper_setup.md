# Cloud Scraper Setup

> Historical migration guide: the migration is complete. The DigitalOcean VPS at `/opt/autosniper` is now the live runtime and data owner. Use `docs/vps_sync_workflow.md` for current deployment practice. Do not assess production freshness from laptop Task Scheduler or laptop CSV timestamps.

## Goal

Move the scheduled scraper work off the laptop and onto an always-on cloud Windows machine, while keeping the current app and pipeline logic as unchanged as possible.

The practical target is:

- daily full pipeline runs even when the laptop is off
- hourly active monitor runs without relying on the laptop being awake
- scraper logs and health reports are easy to inspect
- CSV data is backed up or synced predictably
- failure alerts are sent by Telegram

## Recommended first cloud shape

Use a small Windows VPS first.

Do not start with serverless functions. This project currently depends on browser scraping, Playwright, Chrome, local CSV state, Autotrader session files, and long-running scheduled jobs. A Windows VPS is less elegant, but it is much closer to the current working setup and therefore safer for the first production move.

## Before creating the VPS

Decide how the cloud machine will persist `CSV_data`.

This is the main decision. If the cloud VPS updates CSV files but those files only live on that VPS, the laptop and app will not automatically see the new data.

Recommended simple options:

1. VPS is the scraper source of truth, and it pushes data snapshots to a private Git branch or backup location.
2. VPS writes compressed CSV backups to cloud storage after each successful daily run.
3. VPS and laptop sync `CSV_data` through a deliberate file sync tool.

Avoid turning this on until one of those is chosen.

## VPS requirements

Minimum practical spec:

- Windows Server or Windows 11 VPS
- 2 vCPU
- 4 GB RAM minimum, 8 GB preferred
- 60 GB disk minimum
- stable outbound internet
- ability to run Task Scheduler
- interactive desktop access for visible-browser Autotrader session setup

## Install checklist

Install these on the VPS:

- Git
- Python matching the local project version, preferably Python 3.11+
- Google Chrome
- PowerShell 7 optional, normal Windows PowerShell is acceptable

Then clone the repo:

```powershell
cd C:\Users\Administrator\Desktop
git clone <repo-url> autosniper-main
cd autosniper-main
```

Create the virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\pip.exe install -r requirements.txt
.\venv\Scripts\python.exe -m playwright install chrome
```

If the project uses the system Chrome channel rather than Playwright's bundled browser, confirm Chrome opens normally on the VPS desktop.

## Files and secrets to copy

Copy only what is needed. Do not copy random cache folders without checking.

Required or likely required:

- `.streamlit/secrets.toml`, if the app or scripts use it
- Telegram environment variables:
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
- Autotrader session files:
  - `autotrader_isolated/output/storage_state.json`
  - `autotrader_isolated/output/autotrader_cookie.txt`
- governed data required for pricing:
  - `CSV_data/restricted/curves.csv`
  - other governed maps/configs under `CSV_data/restricted/` if not already in Git

The exact CSV copy depends on the data sync decision. For a first migration, copy the current `CSV_data` folder once, then let the VPS become the scraper writer.

## Environment variables

Set machine-level or user-level environment variables for the scheduled task user:

```powershell
[Environment]::SetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "<token>", "User")
[Environment]::SetEnvironmentVariable("TELEGRAM_CHAT_ID", "<chat-id>", "User")
[Environment]::SetEnvironmentVariable("AUTOSNIPER_LOCAL_TIMEZONE", "Australia/Sydney", "User")
```

Open a new PowerShell window afterward so the variables are loaded.

## Smoke tests

Run these from the repo root.

Check project memory:

```powershell
.\venv\Scripts\python.exe scripts\project_memory.py check
```

Check imports and core data paths:

```powershell
.\venv\Scripts\python.exe -c "from shared.data_loader import dataset_path; print(dataset_path('sold_cars.csv'))"
```

Run a daily smoke test before scheduling the full daily job:

```powershell
.\venv\Scripts\python.exe scripts\scheduled_jobs.py --job daily-smoke
```

Run the hourly monitor once:

```powershell
.\venv\Scripts\python.exe scripts\scheduled_jobs.py --job hourly-monitor
```

After each run, inspect:

```text
output/health/scraper_health.json
logs/
status/metrics.json
```

## Scheduled tasks

Prefer calling `scripts\scheduled_jobs.py` directly through the project venv.

Daily:

```powershell
.\venv\Scripts\python.exe scripts\scheduled_jobs.py --job daily
```

Hourly:

```powershell
.\venv\Scripts\python.exe scripts\scheduled_jobs.py --job hourly-monitor
```

The existing local docs also mention wrapper scripts and task registration in `docs/automation_schedule.md`. Use those only if they are confirmed to point at the VPS repo path.

## Suggested schedule

Use Australia/Sydney local time unless there is a reason to change.

- Daily full run: once per day in the morning
- Hourly monitor: every hour while auctions are active

The daily run can take a while. Avoid scheduling hourly jobs in a way that fights the daily lock. The current runner has lock handling, but overlapping jobs still create noisy skipped runs.

## Data sync options

### Option A: Git data branch

The VPS commits selected CSV outputs to a private data branch after successful daily runs.

Pros:

- easy to inspect changes
- easy to roll back
- simple disaster recovery

Cons:

- CSV churn can make Git noisy
- large files can become painful

### Option B: Cloud storage backups

The VPS zips the important data folders and uploads them after daily success.

Pros:

- simple backup model
- less Git noise
- good for historical snapshots

Cons:

- needs a restore workflow
- harder to review individual row changes

### Option C: File sync

The VPS syncs `CSV_data` to a shared folder.

Pros:

- easiest mental model

Cons:

- accidental two-way sync conflicts are dangerous
- less auditability

Recommended first choice: OneDrive zip backups. Avoid casual two-way sync.

## OneDrive backup script

The repo includes:

```text
scripts/backup_runtime_data.py
scripts/backup_runtime_data.ps1
```

It creates a timestamped zip containing the key runtime folders:

```text
CSV_data/scrapers/
CSV_data/restricted/
CSV_data/ai/
CSV_data/model_audit/
CSV_data/reports/
status/
output/health/
logs/scheduled/
```

On Linux/VPS, set `AUTOSNIPER_BACKUP_DIR` in the service environment and test the same interpreter used by the scheduler:

```bash
/opt/autosniper/.venv/bin/python scripts/backup_runtime_data.py --backup-dir /opt/autosniper-runtime-backups
```

The Python command creates the zip and verifies its CRC, required files, and core CSV row counts before returning success. Keep the backup directory outside `/opt/autosniper`; archives are written atomically with private file permissions.

On Windows, set the backup directory:

```powershell
[Environment]::SetEnvironmentVariable(
    "AUTOSNIPER_BACKUP_DIR",
    "C:\Users\Administrator\OneDrive\AutoSniperBackups",
    "User"
)
```

Open a new PowerShell window, then test:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup_runtime_data.ps1
```

The daily runner calls this backup script automatically after a successful full daily pipeline when `AUTOSNIPER_BACKUP_DIR` is set:

```powershell
.\venv\Scripts\python.exe scripts\scheduled_jobs.py --job daily
```

If `AUTOSNIPER_BACKUP_DIR` is not set, the daily runner skips backup creation and prints a skip message.

You can also pass the folder explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup_runtime_data.ps1 -BackupDir "C:\Users\Administrator\OneDrive\AutoSniperBackups"
```

By default, the backup does not include Autotrader cookie/session files. If a deliberate full scraper-state backup is needed, use:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup_runtime_data.ps1 -IncludeAutotraderSession
```

Treat that zip carefully because it may include session material.

For automatic daily backups that include those files, set:

```powershell
[Environment]::SetEnvironmentVariable(
    "AUTOSNIPER_BACKUP_INCLUDE_AUTOTRADER_SESSION",
    "1",
    "User"
)
```

## Backup verification

The repo includes a safe verifier:

```text
scripts/verify_runtime_backup.ps1
```

It extracts a backup zip into a temporary folder, checks that the key files exist, loads the important CSVs, prints row counts, and then removes the temporary extraction folder. It does not overwrite live project files.

Verify the latest backup from `AUTOSNIPER_BACKUP_DIR`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_runtime_backup.ps1
```

Verify a specific zip:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_runtime_backup.ps1 -BackupZip "C:\Users\Administrator\OneDrive\AutoSniperBackups\autosniper-runtime-YYYYMMDD-HHMMSS.zip"
```

Treat a backup as usable only if at least these load successfully:

```text
CSV_data/scrapers/sold_cars.csv
CSV_data/restricted/sold_cars_restricted.csv
CSV_data/ai/ai_listing_valuations.csv
```

## Health checks

A cloud run should be considered healthy only if:

- daily job exits successfully
- hourly job exits successfully while the VPS is awake and logged in
- `output/health/scraper_health.json` updates after runs
- sold count changes when new sold rows exist
- active count is plausible
- Telegram sends failure alerts
- Autotrader session still works in visible-browser mode

## Sold-price guardrail

After the sold-price repair, the cloud runner must preserve the rule:

Only verified final sale prices should enter `CSV_data/scrapers/sold_cars.csv`.

Rows with ended/live bid evidence but no verified final sale price should go to pending review instead of polluting sold history.

Useful checks after the first cloud daily run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_update_bids.py tests\test_update_master_snapshot.py tests\test_repair_sold_prices_from_rescrape.py -q
```

## Cutover plan

1. Build VPS and install dependencies.
2. Clone repo and copy required secrets/session files.
3. Copy current data baseline.
4. Run project memory check.
5. Run `daily-smoke`.
6. Run `hourly-monitor`.
7. Confirm health report, logs, active rows, sold rows, and AI cache look sane.
8. Choose and test data backup/sync.
9. Enable scheduled hourly.
10. Enable scheduled daily.
11. Disable laptop scheduled tasks once the VPS proves stable.

Do not leave both laptop and VPS running daily production jobs against separate CSV copies unless there is a deliberate merge strategy.

## Recovery notes

If a run fails after expensive scraping work, do not blindly rerun the whole daily job. Check the failed stage and resume deliberately where possible.

If Autotrader fails with `403`, refresh the visible-browser session on the VPS desktop and regenerate:

```text
autotrader_isolated/output/storage_state.json
autotrader_isolated/output/autotrader_cookie.txt
```

If sold prices look suspicious, stop the daily promotion path and compare against known listing URLs before allowing more rows into `sold_cars.csv`.
