# Automation Schedule

## Daily Full Pipeline

Run once per day:

```cmd
scripts\run_daily.cmd
```

This job runs:
- Grays link extraction
- vehicle detail extraction
- bid refresh
- Autotrader scrape
- master database update
- full active-listing AI revaluation

## Hourly Active Monitor

Run once per hour:

```cmd
scripts\run_hourly_monitor.cmd
```

This job runs:
- active bid refresh for the current live active set
- change detection on bid, bid count, time remaining, and status
- AI revaluation for changed listings
- AI revaluation for listings with stale or missing active analysis

## Telegram Alerts

Telegram alerts require these environment variables:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

The active monitor now sends alerts when:
- a listing becomes bid-ready (`action_label = Buy`)
- a previously bid-ready listing is no longer marked `Buy`

Alert state is tracked in:

```text
CSV_data/ai/telegram_alert_state.csv
```

Alert history is logged in:

```text
CSV_data/ai/telegram_alert_log.csv
```

## Recommended Scheduler Setup

Windows Task Scheduler:
- schedule `scripts\run_daily.cmd` once daily
- schedule `scripts\run_hourly_monitor.cmd` every hour

You can register both tasks automatically with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_automation_tasks.ps1
```

Keep the old VIC-specific jobs only if you still want those narrower refreshes:
- `scripts\run_vic_12h.cmd`
- `scripts\run_vic_hourly.cmd`
