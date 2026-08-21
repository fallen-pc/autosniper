import pandas as pd

from scripts import build_apify_batch9_curves as batch9


def test_batch9_builder_uses_tracked_evidence_and_exact_lane_counts():
    assert batch9.RETAIL_PATHS
    assert all(path.exists() for path in batch9.RETAIL_PATHS)
    assert all("quality" not in path.parts for path in batch9.RETAIL_PATHS)

    retail = batch9._load_retail()
    retail["year_numeric"] = pd.to_numeric(retail["year"], errors="coerce")
    retail["odometer_numeric"] = pd.to_numeric(retail["odometer"], errors="coerce")
    retail["price_numeric"] = pd.to_numeric(retail["price"], errors="coerce")

    counts = {
        lane["key"]: len(batch9._select_market(retail, lane))
        for lane in batch9.LANES
    }
    assert counts == {
        "bmw_x5_sdrive25d_f15_auto_diesel": 39,
        "nissan_micra_st_k13_auto_petrol": 7,
    }


def test_batch9_builder_uses_pinned_live_grays_evidence():
    sold = pd.read_csv(batch9.SOLD_PATH, low_memory=False)
    counts = sold.groupby(["make", "model"])["vin"].nunique().to_dict()
    assert counts == {("bmw", "x5"): 12, ("nissan", "micra"): 8}
