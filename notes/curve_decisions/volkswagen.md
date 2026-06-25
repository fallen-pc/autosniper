# Volkswagen Curve Decisions

## Golf VI Comfortline Hatch Auto Petrol/Diesel

- `volkswagen_golf_comfortline_vi_hatch_auto_petrol` and `volkswagen_golf_comfortline_vi_hatch_auto_diesel` are saved V2 base curves for Mk6/VI Golf Comfortline automatic hatch evidence.
- `volkswagen_golf_comfortline_petrol_auto_hatch_vi` and `volkswagen_golf_comfortline_diesel_auto_hatch_vi` are the matcher tags that feed those base curves through the V2 group map.
- The 2026-06-23 Carsales/Apify scrape supplied `15` VI 118TSI Comfortline petrol automatic hatch rows and `12` VI 103TDI Comfortline diesel automatic hatch rows.
- The saved grids include high-km buckets `225000` and `300000` because the evidence and live active rows reach beyond the ordinary 200k grid.
- GTI, Golf R/R, Trendline, Highline, wagon, manual, and opposite-fuel rows remain separate.
- These are retail resale curves from private Carsales asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.

## Golf V Comfortline And VI Trendline Hatch Auto Petrol

- `volkswagen_golf_comfortline_v_hatch_auto_petrol` is the saved V2 base curve for Golf V Comfortline automatic petrol hatch evidence.
- `volkswagen_golf_trendline_vi_hatch_auto_petrol` is the saved V2 base curve for Golf VI 90TSI Trendline automatic petrol hatch evidence.
- `volkswagen_golf_comfortline_petrol_auto_hatch_v` and `volkswagen_golf_trendline_petrol_auto_hatch_vi` are the matcher tags that feed those base curves through the V2 group map.
- The 2026-06-25 pass uses existing private Carsales/Apify evidence and historical Grays sold volume only for prioritisation.
- GTI, Golf R/R, Highline, wagon, manual, diesel, and other generation rows remain separate.
- These are retail resale curves from private Carsales asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.

## Golf V GTI Hatch Auto Petrol

- `volkswagen_golf_gti_v_hatch_auto_petrol` is the saved V2 base curve for Golf V/A5 GTI automatic petrol hatch evidence.
- `volkswagen_golf_gti_petrol_auto_hatch_v` is the matcher tag that feeds the base curve through the V2 group map.
- The 2026-06-26 pass uses `8` clean private Carsales/Apify GTI V automatic petrol hatch rows spanning `2007`-`2009`; historical Grays sold volume was used only to prioritise the target.
- Golf VI GTI, Golf R/R32, Comfortline, Trendline, Highline, wagon, manual, and diesel rows remain separate.
- This is a retail resale curve from private Carsales asking evidence only. Grays sold history remains hammer-bid evidence, not repricing evidence.
