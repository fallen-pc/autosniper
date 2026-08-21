# Lane evidence from verified exits — August 16, 2026

## Why the tagger refuses 10,567 confirmed exits

It is not a bug. `config/allowed_variants.csv` holds **223 entries**, and the tagger only places
a vehicle into a lane that has been explicitly defined. Every refusal is correct behaviour.

Reason codes across the 10,567:

| reason | rows | share |
|---|---|---|
| `OUT_OF_SCOPE` | 7,126 | 67.4% |
| `DISALLOWED_VARIANT` | 1,701 | 16.1% |
| `OUT_OF_SCOPE_YEAR` | 781 | 7.4% |
| `AMBIG_BADGE` | 734 | 6.9% |
| `BAD_PARSE` | 155 | 1.5% |
| `AMBIG_FUEL` / `AMBIG_TRANS` | 70 | 0.7% |

Spec data is not the problem — year/make/model/body are ~0% blank on the refused rows.

`OUT_OF_SCOPE` fires where the candidate list from `allowed_variants` empties. Attributing the
7,126 to the stage that empties it:

| stage | rows | fix |
|---|---|---|
| model absent | 3,788 (53%) | new lane |
| make absent | 1,887 (27%) | new make |
| body absent | 1,042 (15%) | extend a model already covered |
| fuel/trans absent | 409 (6%) | extend a model already covered |

## Important dependency

`allowed_variants.csv` and `curves.csv` are in lockstep — 1,822 rows tag successfully and 1,803
resolve a curve_tag, essentially 1:1. Unlocking a lane needs **both** an allowlist entry **and**
a curve. Adding allowlist entries alone produces canonical tags that then fail curve resolution.

## `scripts/build_lane_evidence.py`

Summarises confirmed exits for one make/model/body onto the standard 30/60/100/150/200k curve
grid, using the canonical tagger's own normalisers. That matters: raw Autotrader body strings
for one Hilux include "Double Cab Pick Up", "Dual Cab Pick-up", "Dual Cab Utility", "Double Cab
Chassis" and "Dual Cab Chassis" — naive string matching finds none of them.

**EVIDENCE ONLY.** Project policy is that curve prices are Carsales/Apify-led and Autotrader is
comparison evidence. These are also ASKING prices. Use this to decide whether a lane is worth
building and what shape it has, not as curve input.

## Lanes scoped

| lane | n | median | variants >=25 obs | km coverage (30/60/100/150/200k) |
|---|---|---|---|---|
| ford ranger dualcab_ute | 343 | $39,950 | 4 (168 rows) | 73/37/77/60/96 |
| toyota kluger wagon | 265 | $42,490 | 4 (130 rows) | 48/55/59/47/56 |
| toyota hilux dualcab_ute | 263 | $44,990 | 2 (177 rows) | 22/35/69/57/80 |
| toyota hiace van | 117 | $37,999 | 1 (43 rows) | 16/9/22/24/46 |
| nissan navara dualcab_ute | 110 | $26,384 | 0 | 14/6/14/21/55 |

Note these counts exceed the earlier stage-attribution figures (e.g. Ranger 343 vs 80). The
diagnostic counted only rows failing at the *body* stage; the evidence files carry all available
exits for the lane, which is the right number for curve building.

### Hilux dual cab, per variant

Dual cab is **263 of 436** Hilux exits (60%). Only `cab_chassis` (92) is currently covered.

    SR (4X4)   n=102, 2007-2023
       60k  n= 9   median $51,990
      100k  n=29   median $47,990
      150k  n=32   median $42,982
      200k  n=31   median $32,000   (p25 $22,689 - p75 $39,482, very wide)

    SR5 (4X4)  n=75, 1996-2024
       60k  n=10   median $60,240
      100k  n=17   median $57,980
      150k  n=11   median $48,990
      200k  n=34   median $29,990

Clean monotonic decay on both; SR5 sits consistently above SR as expected. The 30k anchor is
thin on both (n=1 and n=3).

## Cautions

* **The 200k bucket is a catch-all** for everything above 150k, so it pools a 160k 2018 truck
  with a 300k 2007 one. Its p25-p75 spread is far wider than any other bucket. This mirrors the
  known high-km problem already recorded against the existing Hilux lane.
* **Do not pool premium trims.** Hilux Rogue $62,990, Rugged X $58,245, GR-Sport $76,685,
  Rogue 48V $72,490 would badly distort an SR/SR5 curve; Workmate $27,900 likewise from below.
* **Navara has no variant with >=25 observations** — it is the weakest of the five and probably
  not worth building yet.

## Priority

Ranger dual cab and Kluger wagon have the best variant depth (4 variants each at >=25 obs).
Hilux dual cab has the strongest per-variant structure (SR 102, SR5 75) and the clearest decay.

## Next

1. Gather Carsales/Apify evidence for the chosen lane and build the curve there.
2. Add the matching `allowed_variants` entries.
3. Rebuild the ledger; usable observations grow with each lane.
4. Then the join to Grays sold rows on `curve_tag` and `scripts/evaluate_buy_selection.py`.
