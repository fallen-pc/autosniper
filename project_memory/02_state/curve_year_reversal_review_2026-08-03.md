# Curve year-reversal review - 2026-08-03

The 13 governance warnings for the three curve families below were reviewed against the saved curve rows and the retained market evidence. They are accepted evidence-shaped warnings, not permission to smooth or reprice the curves automatically.

## Mercedes ML320 CDI W164

- Warnings: the 2007 `price_low` is $100 below 2005 at 225,000 km ($5,600 versus $5,700) and 300,000 km ($4,400 versus $4,500).
- This is a low-band-only, $100 tail reversal. The mid/high bands do not reverse at those cells.
- The retained Autotrader market snapshot includes exact base W164 ML320 CDI asks at 2007/274,689 km/$8,988 and 2007/321,781 km/$5,990. A 2009/$9,990 row is explicitly Luxury trim and remains outside the base curve.
- Decision: accept the two warnings as immaterial rounding in sparse high-kilometre low bands. Do not invent a $100 uplift merely to silence governance.

## Subaru Outback 2.5i B5A/4GEN

- Evidence source: `CSV_data/scrapers/carsales_outback_25i_b5a_20260728.json` (CSV-formatted retained Apify output), 15 exact private 2.5i 4GEN automatic AWD rows.
- The 300,000 km 2009-to-2012 reversal is supported by high-kilometre asks: 2009/287,000 km/$5,500 versus 2012/294,000 km/$4,900 and 2012/322,300 km/$2,500.
- The 2012-to-2014 reversal around 100,000-150,000 km reflects the retained asks rather than an age assumption: 2012/129,000 km/$17,000 versus 2014/106,000 km/$12,800. The 2014 sample is thin (two exact rows), so it must not be smoothed without new evidence.
- Decision: accept the eight warnings and retain the curve. Reconsider only when fresh exact private evidence materially expands the 2014 sample.

## Subaru XV 2.0i-S G4X

- Evidence source: `CSV_data/scrapers/carsales_xv_20is_g4x_20260728.json` (CSV-formatted retained Apify output), 22 exact private 2.0i-S G4X automatic AWD rows.
- The 60,000 km 2014-to-2016 reversal is supported by the low-kilometre asks used around those anchors: 2013/47,000 km/$19,800 and 2015/46,000 km/$18,700, followed by 2016/64,000 km/$18,200. The saved mids ($19,500 versus $18,500) preserve that observed pocket.
- Decision: accept the three warnings. Do not force year monotonicity over the retained same-lane market evidence.

## Audit contract

- Governance warnings are review prompts, not automatic errors.
- A future audit should report these 13 rows as previously reviewed unless the curve cells or supporting evidence change.
- Any repricing must be a separate evidence-backed curve task and must preserve the exact trim/generation/powertrain boundaries above.
