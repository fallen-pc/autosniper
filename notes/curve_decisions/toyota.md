# Toyota Curve Decisions

## Corolla Ascent Sedan

Current working interpretation:
- `toyota_corolla_ascent_petrol_auto_sedan_zre152r` is an Ascent sedan lane, not a generic ZRE152R sedan lane.
- `Conquest` is a separate trim and must not be used as fallback evidence for Ascent.

Implementation note:
- `Conquest` is now excluded from Corolla Ascent tagging for the `zre152r`, `zre172r`, and `zre18x` Ascent lanes.
- After retagging, the raw Grays `zre152r` Ascent sold lane contains `42` Ascent rows and no Conquest rows.

## V2 Base Curve Source Of Truth

Current working interpretation:
- When a V2 match tag maps to a saved base curve, the base curve is the source of truth.
- Matcher tags may still appear in tagged evidence and coverage reports, but they should not carry separate saved curve rows when the base exists.

Implementation note:
- Removed stale duplicate matcher-tag curve rows for `toyota_corolla_ascent_petrol_auto_hatch_zre18x`, `toyota_corolla_ascent-sport_petrol_auto_hatch_zre18x`, and `toyota_yaris_yr_petrol_auto_hatch_ncp90r`.
- The Toyota hatch split still resolves through `toyota_corolla_ascent_zre182r_hatch_auto_petrol` and `toyota_corolla_ascent-sport_zre182r_hatch_auto_petrol`.
- The Yaris matcher still resolves through `toyota_yaris_ncp90r_hatch_auto_petrol`.
