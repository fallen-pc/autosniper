# Carsales Apify Curve Evidence Procedure

## Purpose

Carsales private listing evidence is the preferred retail asking-price source for new resale curves and new body/generation/badge lanes. Grays sold history remains hammer-bid/buy-side evidence only and must not be used to reprice retail resale curves.

## Known-good Apify workflow

Run the local coverage preflight before any paid scrape. The runner now does
this by default and blocks/warns when a target mostly duplicates existing
governed curves.

```powershell
.\.venv_local\Scripts\python.exe scripts\carsales_scrape_preflight.py `
  --make isuzu `
  --model mu-x `
  --body-type wagon `
  --seller-type private `
  --fuel-type diesel
```

Only use `--allow-covered-refresh` for a deliberate refresh, extension, or
validation run where duplicate coverage is expected and accepted.

Use `scripts/run_carsales_apify.py` with broad, reliable filters and then filter locally from the normalized CSV.

Recommended command shape:

```powershell
$env:APIFY_TOKEN = "<token>"
.\.venv_local\Scripts\python.exe scripts\run_carsales_apify.py `
  --make holden `
  --model commodore `
  --body-type wagon `
  --seller-type private `
  --condition used `
  --max-items 120 `
  --max-total-charge-usd 0.80 `
  --poll-until-finished `
  --import-results `
  --import-partial
Remove-Item Env:APIFY_TOKEN
```

Use one run per broad body slice when practical:
- sedan
- wagon
- ute/cab chassis only when that body lane is part of the target

For a final sweep on a make/model family, omit `--body-type` and keep a firm cost cap.

## What not to rely on

- Do not rely on the actor's `transmission` or `fuelType` filters until verified for the specific run; they returned zero rows for Holden Commodore even when matching rows existed.
- Do not use guessed Carsales SEO URLs as a source of truth. The June 2026 VE Series II SV6 URL attempts returned unrelated broad rows and had to be discarded.
- Do not treat `SV6`, `SV6 Z Series`, `Z Series`, `Equipe`, `International`, `Lumina`, `Acclaim`, `Executive`, and other badges as interchangeable unless a curve note explicitly records a combined lane decision.

## Local output

Imported rows are normalized into:

```text
CSV_data/quality/carsales_apify_listings.csv
```

This file is local staging evidence. It is ignored by git and should be summarized into curve decision notes, not blindly committed.

Useful quick summaries:

```powershell
Import-Csv CSV_data/quality/carsales_apify_listings.csv |
  Group-Object make,model,series,badge,body_type,transmission |
  Sort-Object Count -Descending |
  Select-Object -First 60 Count,Name |
  Format-Table -AutoSize
```

```powershell
Import-Csv CSV_data/quality/carsales_apify_listings.csv |
  Where-Object {$_.make -eq "Holden" -and $_.model -eq "Commodore" -and $_.series -eq "VE Series II"} |
  Select-Object year,badge,series,body_type,transmission,fuel_type,price,odometer,state,market_indicator |
  Sort-Object badge,body_type,{[int]$_.year},{[int]$_.odometer} |
  Format-Table -AutoSize
```

## Curve-readiness threshold

Use judgement, but the current practical rule is:

- `10+` clean same-lane private rows: usually enough for a conservative curve.
- `6-9` clean rows: usable only if the lane is important and the curve is explicitly conservative/thin.
- `<6` clean rows: scrape more or leave as a target, unless the user explicitly accepts a provisional curve.

Clean same-lane rows must align on:
- make/model
- series/generation
- badge or combined-badge decision
- body type
- transmission
- fuel type
- seller type/private market

## Commodore June 2026 scrape notes

Known-good broad Holden Commodore runs used:
- broad sedan private used
- broad wagon private used
- final broad make/model private used sweep

The final broad sweep cost about `$0.74`, imported `100` rows, and added `8` new unique rows after dedupe. It improved VZ and VE Series II Omega wagon context but did not materially improve VE Series II SV6 sedan.

Current post-scrape Commodore target status:
- `VE Series II SV6 wagon automatic petrol`: usable but thin; `9` plain SV6 wagon rows, with `4` additional SV6 Z Series wagon rows kept separate unless deliberately merged.
- `VE Series II SV6 sedan automatic petrol`: still thin; `4` clean automatic sedan rows plus `1` manual row that must not feed the automatic curve.
- `VZ Executive sedan/wagon automatic petrol`: possible next budget lane; `5` sedan and `6` wagon rows, but scrape/direct review should decide whether sedan and wagon can be separate or need a combined conservative lane.
- `VZ SV6 sedan automatic petrol`: thin; `5` rows.
