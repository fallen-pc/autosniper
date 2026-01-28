AutoSniper Key Semantics (Final)

1. Pipe key is the ONLY join key
All joins across:
- curves
- active listings
- sold listings
- AI analysis
- UI filters
use only:
model | group_key | series | anchor_year

Example:
camry | sedan_petrol_auto | ASV70R | 2020

2. Canonical tags are classification only
Canonical tags:
- determine eligibility
- apply spec rules
- resolve series/year guards
They must not be used as joins.

3. Pipe keys are immutable
Once written:
- they are never rewritten
- never corrected
- never silently upgraded
If scope changes, create a new pipe key.

4. Curves are market memory
Curves:
- come from Carsales valuation tool only
- never from auction results
- never from AI inference
- never auto-generated
Interpolation is allowed.
Extrapolation is not.

5. Sold data never sets price
Sold auctions:
- validate liquidity
- validate spread
- influence risk
They never define resale price.
Curves do.

6. One vehicle = one pipe key
If two listings differ materially (engine, drivetrain, body, transmission):
- they must not share a pipe key
Reduce curve count via:
- multipliers
- overlays
- not key pollution
