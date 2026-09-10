# Slattery integration repair

Implemented on 11 September 2026 following the Grays/Slattery reassessment. Grays can advertise a Slattery vehicle through a referral wrapper; the selling platform still determines the detail format, auction lifecycle and buyer charges.

## Discovery and identity

The external-auction scraper traverses Slattery's public motor-vehicle API and the Grays Motor Vehicles/Motor Cycles search. It reconciles unique records against pagination metadata and stops with an incomplete result if pages repeat, totals change, required metadata is missing, requests fail or a configured cap prevents exhaustion.

Numeric asset and auction IDs are reconciled with Salesforce-style IDs only through explicit data on the matching Slattery page. The full canonical URL, including auction context and unknown query parameters, remains the listing identity. The scraper removes known marketing parameters, retains original URLs and discovery surfaces, and merges that provenance across scheduled seed refreshes. A historical seed does not count as a newly discovered listing.

## Details and lifecycle

The detail path reads the public hydration response and matches the requested asset and auction before extracting vehicle identity, kilometres, VIN, location, condition, registration, current bid and effective closing time. It does not take prices or details from recommended vehicles elsewhere on the page.

The active monitor requires an explicitly active, complete Slattery record with a future closing timestamp. Missing identity, kilometres, VIN, location/state or condition evidence marks the detail incomplete. A successful HTTP request alone does not establish completeness. Upcoming, closed, unknown and incomplete records cannot enter the active Slattery candidate set.

Closed auctions retain their observed last bid without creating a sold date or final sale price. Historical Slattery sale ingestion requires an explicit Sold status, sold date and positive final sale price. Dealer-only plates remain unregistered for this private buyer, preserving roadworthy costs and preventing a registration transfer fee from being assumed.

## Fees and valuation

Auction fees are selected by the actual hostname and consistent operator metadata. A Slattery URL containing `utm_source=grays` uses Slattery fees. Conflicting operator evidence requires Review.

Slattery charges come from the matched asset's GST-inclusive `chargePrices` rows, bound to its URL and observation time. The calculation sums applicable fixed charges or the greater of percentage/minimum charges, and includes the public calculator's 1.65% card surcharge when bid plus premium is below $5,000. Missing, malformed or incomplete schedules require Review with a zero recommended bid and unavailable cost/profit estimates. The generic Slattery website fallback is not accepted as lot-specific evidence.

The proxy bid solver checks fee discontinuities as well as the final cap, including repair costs, so a lower winning price cannot violate the same profit floor. Fee evidence participates in the valuation cache key. Live and historical calculations share the same fee rules.

## Verification

Live observations were captured on 11 September 2026 Sydney time:

- Discovery traversed 19 Slattery API pages and reconciled all 325 advertised vehicle records. Seven Grays search pages reconciled 259 total cards; five were Slattery referrals, all merged with their native listing identities. The crawl made 31 public requests with no incomplete reasons or caps reached. This proves discovery at that observation time, not complete detail extraction for all 325 vehicles.
- The actual Playwright browser-recycling loader was exercised with a one-page cap and correctly reported incomplete discovery.
- The final detail probe used the production-shaped batch path for 11 lots across WA, QLD, NSW, SA and VIC: 11 successful responses, 11 usable fee schedules, two Active, eight Upcoming and one Closed. Ten had complete required details. One council Camry lacked an odometer and remained incomplete.
- The two QLD lots used a valid custom 7.7% GST-inclusive schedule starting at $0.01. Each calculated $462 in buyer charges at a $6,000 bid. The sampled standard schedule calculated $814 at the same bid.
- Regression coverage includes alias ambiguity, unrelated-page records, changing pagination, missing required fields, closing extensions, dealer-only registration costs, fee boundaries, lower-price proxy wins, cache invalidation, live/replay parity, persisted provenance and closed-versus-sold handling.
- Final full suite: 1,334 passed, with two existing pandas FutureWarnings. Readiness and governance passed; governance covered all 446 observed tags with no schema/dataset changes and 13 existing monotonicity warnings, zero errors.

Public source examples: [Slattery motor vehicles](https://slatteryauctions.com.au/categories/motor-vehicles), [Grays vehicle search](https://www.grays.com/search/automotive-trucks-and-marine/motor-vehiclesmotor-cycles?tab=items), [closed RAV4](https://slatteryauctions.com.au/assets/137614?auctionId=10301), [custom-fee RAV4](https://slatteryauctions.com.au/assets/140397?auctionId=11023).

Local evidence is retained under `output/playwright/slattery-discovery-20260911/`, `output/slattery-live-verification/final-summary.json` and `output/slattery_fee_evidence/`. The test fixture uses a synthetic VIN and registration. Captured runtime evidence is excluded from the source commit.

Implementation commit `4bbc89f` was prepared on `codex/slattery-integration-20260911`, based on `origin/main` at `ac1b2b5`. The pre-release production check observed deployed commit `ac1b2b5` and a successful latest daily run. The owner subsequently authorised memory update, push and governed deployment on 11 September. Release from synchronized `main` using `scripts/deploy_vps.ps1 -Release`; reconcile the actual deployed revision through `/opt/autosniper/status/deployed_commit.txt` and `governed_data_release.json`. A bounded post-release probe writes isolated evidence and does not refresh canonical feeds. Governed schemas, resale curves and native Grays extraction remain unchanged.
