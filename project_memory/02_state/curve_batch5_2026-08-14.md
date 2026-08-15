# Curve batch 5 - 2026-08-14

- Carsales Apify run `Nu8coMBuDLXOwOEUX` succeeded with `874` private listings across Hyundai i45, Nissan Dualis, Ford Mondeo, Volkswagen Golf, Kia Grand Carnival, and Volvo XC60 at a cost of `$1.3967`.
- Added governed curves for Hyundai i45 Active YF, Nissan Dualis ST J10 CVT, Ford Mondeo LX TDCi MC wagon, Volkswagen Golf GTI VI automatic, and Volvo XC60 T5 DZ.
- Exact evidence used: i45 Active `6` retail / `13` unique Grays; Dualis ST `23` retail (`21` used after trimming) / `13`; Mondeo LX TDCi `6` / `12`; Golf GTI VI `10` / `16`; XC60 T5 DZ `9` / `15`.
- Focused matcher and governance tests passed (`29`), the curve validator reported no warnings, and restricted sold coverage increased from `4,829` to `4,920` of `20,267` sold records.
- Held lanes: Volvo XC60 T5 Teknik DZ has only `5` exact private listings despite `13` Grays; Kia Grand Carnival Si VQ remains at `5` deduplicated exact private listings despite the fresh scrape; BMW X5 3.0i E53 from Batch 4 remains held at `5` true 3.0-litre listings after excluding V8 rows.
- The XC60 lane required a narrow canonical-series parser correction: `XC60` is ignored as a model-like token and `DZ` is recognized as the platform series.
