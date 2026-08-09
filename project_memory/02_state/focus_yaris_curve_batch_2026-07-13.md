# Focus/Yaris Curve Batch - 2026-07-13

- Added `ford_focus_trend_lz_hatch_auto_petrol` from 7 clean private Carsales/Apify Focus Trend LZ automatic petrol hatch rows spanning 2015-2016.
- Routed the current no-series 2011 Toyota Yaris YR petrol automatic hatch row to the existing NCP90R YR matcher/base curve by tightening NCP130R matching to require an explicit NCP130R token.
- Kept adjacent lanes separate: Focus LW, Sport, Titanium, Ambiente, ST, XR5, manual, diesel, and non-hatch rows remain excluded; Yaris NCP130R still requires explicit NCP130R evidence.
- Validation passed with focused canonical tagging tests, restricted dataset rebuild, `scripts/update_master.py`, governance coverage/check, curve validation, curve snapshot, and readiness smoke.
- Post-build targeted active audit showed the 2016 Focus Trend and 2011 Yaris YR active rows both classify as `[OK]`.
