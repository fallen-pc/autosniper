# Isuzu Curve Decisions

## MU-X LS-M/LS-U/LS-T SUV Auto Diesel

- `isuzu_mux_lsm_suv_auto_diesel`, `isuzu_mux_lsu_suv_auto_diesel`, and `isuzu_mux_lst_suv_auto_diesel` are separate trim curves for MU-X automatic diesel SUV evidence.
- `isuzu_mux_lsm_diesel_auto_suv_mux`, `isuzu_mux_lsu_diesel_auto_suv_mux`, and `isuzu_mux_lst_diesel_auto_suv_mux` are the matcher tags that feed those base curves through the V2 group map.
- The 2026-06-23 Carsales/Apify scrape supplied `17` LS-M rows, `36` LS-U rows, and `67` LS-T rows.
- The saved grids use anchors `2015`, `2018`, and `2020` with high-km buckets `225000` and `300000` because current active MU-X examples include odometers near `300000`.
- LS-M, LS-U, LS-T, petrol, manual, and non-SUV/body lanes remain separate.
- These are retail resale curves from private Carsales asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.
