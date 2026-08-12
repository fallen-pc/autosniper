# External auction visibility in AI Analysis - 2026-08-11

- Production evidence before the fix: the active monitor had 36 curve-covered listings
  (`31` Grays and `5` Pickles), while AI Analysis loaded none of the five Pickles URLs.
- AI Analysis now reuses the active monitor's external lifecycle loader and shortlist
  eligibility filter instead of reimplementing status, rediscovery, price, and WOVR rules.
- External rows are concatenated only after Grays restricted-group tagging, avoiding
  `canonical_tag` merge suffixes, and odometer/price numerics are refreshed before the
  existing canonical, year, and kilometre curve-coverage checks.
- Both paths continue to value eligible rows through `run_curve_listing_analysis`, keeping
  repair, comparable, bid-policy, and action semantics aligned.
