# Quote batch + researched interim prices — August 19, 2026

Parts 2 and 3 of the "address the 22,902-hit pricing gap right away" pass. Part 1 was the
class-blindness fix (`quote_pipeline_class_blindness_fix_2026-08-19.md`).

## Part 2 — prioritised quote-request batch

`scripts/build_repair_quote_batch.py` reads the top-N MISSING cells from
`repair_pricing_matrix.csv` (real, full-scan occurrence counts) and drafts a properly-scoped
quote request per (canonical, vehicle_class) cell using the now-fixed `needs_pricing()`
infrastructure. Skips a cell if it's already priced or already has an open (non-dead-end)
request, so it's safe to re-run.

**Drafts only — nothing is sent.** Every row is written `status="draft"`. Sending requires the
operator's own channel; this script has no send capability and none was invoked.

Run for the top 20 cells (88.1% of the 22,902-hit gap): **20 new drafts, RQ-0059 to RQ-0078**,
saved to `CSV_data/reports/repair_quote_requests.csv` (untracked, per `.gitignore`). Representative
vehicles used match the existing schedule's own convention (2016 Toyota Corolla / 2016 Mazda
CX-5) plus two chosen from this session's own lane-evidence work (2018 Toyota Hilux SR dual-cab,
2017 Toyota HiAce) rather than invented.

6 tests in `tests/test_build_repair_quote_batch.py`.

## Part 3 — researched interim prices

Two rounds of web research. First round (general "repair cost Australia" queries) produced only
national flat ranges with no class breakdown - explicitly **not used**, since scaling a
small_hatch figure by a guessed size ratio is exactly what the schedule's own validator forbids
("do not invent class multipliers").

Second round targeted each vehicle class directly (ute/SUV/sedan-specific queries, not general
ones) and found four cells with a genuinely different, independently-sourced figure - not the
same national number restated:

| canonical | class | finding | source |
|---|---|---|---|
| corrosion_damage | ute | frame/chassis rust, $2,000-4,000 | [Dinggo](https://www.dinggo.com.au/blog/what-is-the-estimated-cost-of-car-rust-repair) |
| corrosion_damage | medium_suv | wheel-arch panel, $350-600 | [PartCatalog](https://www.partcatalog.com/blogs/body/wheel-arch-repair-panel-replacement-cost-guide) |
| corrosion_damage | small_sedan | same source, same figure (source groups sedan+compact SUV) | as above |
| seat_damage | ute | bench-seat reupholster, $400-800, priced as its own job type | [ServiceTasker](https://servicetasker.com.au/cost-guides/how-much-does-upholstery-repair-cost) |

`cosmetic_surface_damage` and `paint_damage` - the two biggest cells (5,127 and 1,180 hits) -
were searched directly for Hilux/HiAce and came back "contact a local repairer for a quote" both
times. What sources DO break out by size is a *full* respray ($1,800 small car -> $8,000 large
SUV), not single-panel work, which is reported as one flat national range everywhere. Genuine
finding, not a search failure: left MISSING rather than filled with a non-finding.

`scripts/apply_researched_repair_prices.py` wrote the four rows to
`CSV_data/reports/repair_pricing_schedule.csv` (which, unlike most of `CSV_data/`, **is** tracked
in git - a deliberate `.gitignore` carve-out for curated reference data). Every row:
`confidence="low"`, `pricing_method="internal_default"` - never `"repair_quote"` - so these can
never be mistaken for a real supplier quote in the schedule. `notes` cites the source URL and the
matching drafted request id, so whoever reviews a reply from RQ-0074/0076/0077 knows to replace
this row via `pricing_row_from_quote()` rather than leaving both on file.

Verified against `missing_vehicle_classes_for()`: `corrosion_damage` now only missing `van`;
`seat_damage` no longer lists `ute`.

4 tests in `tests/test_apply_researched_repair_prices.py`, including one that would fail loudly
if a future edit ever dropped a citation or broke `low <= default <= high` on one of these rows.

## Full suite

1,012 passed, 1 xfailed after all three parts.

## What's still open

- 16 of the 20 targeted cells have no real evidence yet - the drafted quotes are the path there,
  not more searching (confirmed: a second, class-targeted research round hit the same wall).
- `repair_pricing_matrix.csv` is now slightly stale (4 cells flipped from MISSING to priced) -
  a full rescan is cheap to rerun (`scripts/build_repair_pricing_matrix.py --limit 0`) whenever
  the ledger artifact needs to reflect current state.
- Correction to earlier working assumption: "CSV_data is never committed" is not universally
  true - `repair_pricing_schedule.csv` is a deliberate tracked exception in `.gitignore`
  (curated reference data), unlike quote requests or the generated matrix. Worth tightening the
  commit-conventions memory note to reflect this.
