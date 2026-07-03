# Repair Pricing Workflow - 2026-06-27

- Added a dedicated Repair Pricing page with Needs Pricing, Pricing Schedule, Quote Requests, Quote Responses, and Supplier Evidence tabs.
- Quote requests now support explicit recipients, Gmail sent-message metadata, response text, response source, and response parse status.
- Quote Responses lets operator-pasted supplier replies extract low/default/high prices before promoting reviewed rows into the pricing schedule.
- Repair Review and AI Analysis now feed unmapped repair fragments into a shared review queue so new repair wording can become dictionary-backed pricing candidates.
- Pricing candidates exclude hard-avoid repair canonicals and helper/catch-all canonicals that should not be priced directly, including `body_location_list` and `replacement_required`.
- Generated pricing/quote CSVs under `CSV_data/reports/` remain ignored runtime data unless a curated snapshot is intentionally force-added.
- Supplier-facing quote drafts should ask for a price for one specific repair job only. Do not mention auctions, bidding, reconditioning, pricing schedules, or internal estimating workflow in email copy.
