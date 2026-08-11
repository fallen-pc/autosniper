# Slattery live fields and Manheim access status - 2026-08-11

- Slattery asset pages expose live auction fields in the embedded Next.js payload even when they are absent from visible body text.
- `scripts/scrape_external_auction_sources.py` now scopes bid records to the asset ID in the URL, records the highest bid as `price`, and fills `bids` plus `closesAt` without overwriting visible values.
- Live validation against asset `138753` returned HTTP 200 and extracted price `21100`, bid count `32`, and close time `2026-08-10T06:34:18Z`.
- Manheim remains explicitly blocked: the DigitalOcean VPS returned HTTP 403 for both legacy for-sale paths and alternate auction catalogue paths. No unsupported bypass was added.
