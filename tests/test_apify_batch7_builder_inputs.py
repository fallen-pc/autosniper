import pandas as pd

from scripts import build_apify_batch7_curves as batch7


def test_batch7_builder_uses_complete_tracked_exact_evidence():
    assert len(batch7.RETAIL_PATHS) == 1
    assert batch7.RETAIL_PATHS[0].exists()

    retail = batch7._load_retail()
    retail["year_numeric"] = pd.to_numeric(retail["year"], errors="coerce")
    retail["odometer_numeric"] = pd.to_numeric(retail["odometer"], errors="coerce")
    retail["price_numeric"] = pd.to_numeric(retail["price"], errors="coerce")

    counts = {}
    for lane in batch7.LANES:
        year_min, year_max = lane["years"]
        market = retail[
            retail["make"].fillna("").str.lower().eq(lane["make"])
            & retail["model"].fillna("").str.lower().eq(lane["model"])
            & retail["badge"].fillna("").str.lower().eq(lane["retail_badge"])
            & retail["series"].fillna("").str.lower().eq(lane["retail_series"])
            & retail["engine"].fillna("").str.contains(
                lane["engine"], case=False, regex=True
            )
            & retail["body_type"].fillna("").str.contains(
                lane["body_aliases"], case=False, regex=True
            )
            & retail["transmission"].fillna("").str.contains(
                lane["transmission"], case=False
            )
            & retail["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
            & retail["year_numeric"].between(year_min, year_max)
        ].dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])
        counts[lane["key"]] = len(market)

    assert counts == {
        "hyundai_i30_sx_fd_manual": 9,
        "toyota_camry_csi_sxv20r": 6,
        "ford_falcon_xt_ba": 7,
        "toyota_camry_sportivo_acv40r": 6,
    }
