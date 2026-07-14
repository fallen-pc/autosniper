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
- Pickles, Manheim, and Slattery external auction scrape into `output/external_auction_scrape/daily`
- full active-listing AI revaluation

External auction saved-curve matches are loaded into the same active AI
revaluation path as Grays restricted active rows, so repair parsing, curve
coverage, max-bid logic, and AI Analysis output use the same valuation process.
External rows with settled sale evidence also feed Missed Opportunities through
the same historical replay logic; active/upcoming rows are not treated as missed
opportunities until they have a price and sold/closed date or status.

External auction scrape defaults are intentionally source-specific so the daily
job stays bounded:
- Pickles: 20 list pages, all curve-prefiltered detail rows
- Manheim: 1 list page per configured location, first 25 curve-prefiltered detail rows
- Slattery: current motor-vehicles category, all curve-prefiltered detail rows

Useful overrides:

```text
AUTOSNIPER_EXTERNAL_AUCTIONS_DAILY=0
AUTOSNIPER_EXTERNAL_PICKLES_PAGES=20
AUTOSNIPER_EXTERNAL_PICKLES_DETAILS=0
AUTOSNIPER_EXTERNAL_MANHEIM_PAGES=1
AUTOSNIPER_EXTERNAL_MANHEIM_DETAILS=25
AUTOSNIPER_EXTERNAL_SLATTERY_PAGES=0
AUTOSNIPER_EXTERNAL_SLATTERY_DETAILS=0
AUTOSNIPER_EXTERNAL_AUCTIONS_OUTPUT_DIR=output\external_auction_scrape\daily
```

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
- AI Analysis marks a current active listing as `action_label = Buy`
- a listing previously marked `Buy` by AI Analysis is no longer marked `Buy`

Telegram does not run a separate buying policy. It reports the saved AI Analysis
row from `CSV_data/ai/ai_listing_valuations.csv`; the only extra guard is that
the URL must still be present in current active listings and absent from
sold/referred data.

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
