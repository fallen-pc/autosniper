# Variant filtering in CompsEngine — 2026-08-29

## What changed
Added variant-level filtering to `shared/comps_engine.py` to prevent cross-spec
contamination in comparable sales pools (e.g. Hilux SR and SR5 previously pooled
together despite a ~$10k price gap).

## Key design decisions
- `_variant_family(text)` normalises the variant string to its first informative token
  (e.g. "SR5 Double Cab" → "sr5"). Tokens in `_VARIANT_NOISE` (body/drivetrain
  descriptors like "4wd", "diesel", "auto") are skipped.
- `_prepare_dataset()` now adds a `variant_family` column to the historical data.
- `_initial_pool()` tries the same-variant-family subset first. It only uses that
  subset if it has at least `config.min_comps` rows; otherwise falls back to the full
  make/model pool unchanged.
- This is backward-compatible: if the dataset has no `variant` column, or the subject
  row has no variant, the fallback triggers silently.

## Files changed
- `shared/comps_engine.py` — `_variant_family`, `_VARIANT_NOISE`, `_prepare_dataset`,
  `_initial_pool`
- `tests/test_comps_engine.py` — `TestVariantFamily`, `TestVariantFilteringInComps`
