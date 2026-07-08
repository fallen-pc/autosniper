# Ops Reliability Runbook

Target: close the two remaining automation gaps from the 2026-07-08 completeness audit —
Windows Task Scheduler reliability and the Autotrader headless `403`. Everything here is
designed to run on the owner laptop. Each step ends with a verification command; do not
move to the next step until the current one verifies.

---

## Part 1 — Task Scheduler hardening

### Current state (verified 2026-07-08)

`scripts/register_automation_tasks.ps1` already sets `-StartWhenAvailable`,
`-AllowStartIfOnBatteries`, `-DontStopIfGoingOnBatteries`, `-MultipleInstances IgnoreNew`,
and a 72h execution limit. The principal is `-LogonType Interactive`, which is a
deliberate constraint: the Autotrader stage needs a visible browser, and that needs an
interactive desktop session. Do not switch to S4U/service logon while headful scraping
is still required — the task would start reliably and then fail at the Autotrader stage.

App-level protection already exists: `scripts/scheduled_jobs.py` has internet-wait,
missed-daily catch-up, lock TTLs, health reports, and Telegram failure alerts. The
remaining risk is the machine itself: asleep, logged out, or the task not retrying.

### Step 1.1 — Re-register tasks with wake + retry (script updated 2026-07-08)

The registration script now adds `-WakeToRun`, `-RestartCount 3`, and
`-RestartInterval` 10 minutes. Re-run it once from an elevated PowerShell:

```powershell
.\scripts\register_automation_tasks.ps1
```

Verify:

```powershell
Get-ScheduledTask -TaskName "AutoSniper*" | Select-Object TaskName, State
(Get-ScheduledTask -TaskName "AutoSniper Daily Pipeline").Settings |
    Select-Object WakeToRun, RestartCount, StartWhenAvailable
```

Expected: `WakeToRun=True`, `RestartCount=3`, `StartWhenAvailable=True`.

### Step 1.2 — Power plan: keep the machine schedulable

Wake timers only work if sleep is the deepest state and wake timers are allowed.
From elevated PowerShell:

```powershell
# never sleep on AC (0 = never); keep a battery timeout if you want
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
# allow wake timers on AC
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /setactive SCHEME_CURRENT
```

Verify: `powercfg /waketimers` shows the AutoSniper tasks after the next schedule
registration, and `powercfg /query SCHEME_CURRENT SUB_SLEEP RTCWAKE` shows AC value `1`.

Note: `WakeToRun` wakes from sleep, not from powered-off/hibernated-with-fast-startup.
If the laptop is regularly shut down overnight, the 09:00 daily depends entirely on the
app-level catch-up path once the machine is back on — that path is already proven.

### Step 1.3 — Session dependency: logged in vs locked

The Interactive principal needs a logged-in session, but it does not need an unlocked
one for most stages. The open question is only whether the headful Autotrader browser
behaves on a locked desktop. Test deliberately once:

1. Start a manual `--job daily-smoke` run.
2. Lock the workstation (Win+L) while it runs.
3. Check `output/scraper_health/` and the Autotrader stage result afterwards.

If the Autotrader stage succeeds while locked: lock freely; the only hard requirement
is "logged in". If it fails while locked: keep the session unlocked during the 09:00
window, or move that stage to the cloud VPS plan (`docs/cloud_scraper_setup.md`) when
budget allows.

### Step 1.4 — What NOT to treat as scheduler failure

Per `project_memory/02_state/open_issues.md`: a missed run while the laptop was off,
asleep past wake capability, or logged out is expected behaviour, absorbed by catch-up.
Only repeated misses while the machine was awake and logged in count as scheduler
configuration bugs worth investigating (`Get-ScheduledTaskInfo "AutoSniper Daily
Pipeline"` shows `LastTaskResult` — `0` is success, `0x41303` means never run,
`0x41306` means stopped, anything else decode via `[Convert]::ToString($code, 16)`).

---

## Part 2 — Autotrader headless 403 investigation

### Current state (verified 2026-07-08)

Headful (`--playwright-headful`) with the refreshed storage state works; headless
returns `403`. The scraper (`autotrader_isolated/scrape_first_page.py`) currently:

- pins a static user agent `Chrome/131.0.0.0` (`DEFAULT_HEADERS`) onto every context;
- sets `locale: "en-US"` on an Australian site;
- does not set a timezone, so headless defaults to UTC;
- supports `--playwright-browser chrome` (real Chrome channel) — the likely fix path.

Why this matters: anti-bot vendors score consistency. A pinned `Chrome/131` UA string
combined with client hints (`Sec-CH-UA`) from a different real build, `en-US` +
UTC timezone from an Australian residential IP, plus headless rendering quirks is a
high-confidence bot fingerprint. Headful real Chrome passes because everything matches.

### Experiment sequence

Run each experiment against ONE page with the existing flags, in order, and stop at the
first success. Use the smoke command as the harness each time:

```powershell
python autotrader_isolated\scrape_first_page.py --url "https://www.autotrader.com.au/for-sale/used/vic/melbourne" --storage-state autotrader_isolated\output\storage_state.json --playwright-browser chrome --max-pages 1
```

(headless is the default; only add `--playwright-headful` for the control run)

- **E0 (control)**: current headful command — confirm it still succeeds today before
  changing anything, so failures below are attributable.
- **E1 — real Chrome channel, headless**: `--playwright-browser chrome` without
  `--playwright-headful`. Chrome's new headless mode shares the real browser binary
  and produces a much closer fingerprint than bundled Chromium.
- **E2 — remove the UA/locale mismatch**: E1 plus a code change — when the channel is
  `chrome`, do not override `user_agent`, and set `locale="en-AU"`,
  `timezone_id="Australia/Melbourne"` in `new_context`. This makes the UA, client
  hints, locale, and timezone all self-consistent. (Smallest change: make the UA
  override conditional on `browser_name not in {"chrome", "msedge"}`.)
- **E3 — automation flag**: E2 plus launch arg
  `--disable-blink-features=AutomationControlled` (hides `navigator.webdriver`).
- **E4 — persistent real profile**: switch the fetch to
  `launch_persistent_context(user_data_dir=...)` pointed at a dedicated Chrome profile
  that has browsed Autotrader once. Carries full cookie + fingerprint state. More code,
  so only if E1–E3 all 403.
- **E5 — different engine**: `--playwright-browser firefox` headless. Different
  fingerprint surface entirely; some Kasada-style stacks only fingerprint Chromium.

### Recording results

Add one line per experiment to `project_memory/02_state/open_issues.md` under the
Autotrader item: date, experiment id, status code, and page-count if it got further.
If E1–E5 all fail, stop spending time on it: keep the proven headful scheduled path
and prioritise the VPS migration (`docs/cloud_scraper_setup.md`), where a headful
browser in a persistent session is acceptable anyway.

### Guardrails

- Scraper and extractor surfaces are high-sensitivity (open issue list): make E2/E3/E4
  changes behind the existing CLI flags, never as silent default changes to the daily
  pipeline until a full smoke + one supervised daily run passes.
- Keep request pacing as-is; the 403 is fingerprint-based, not rate-based (first
  request fails). Do not add proxies before exhausting E1–E5 — residential IP is an
  asset here.
