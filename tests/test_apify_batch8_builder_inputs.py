import pandas as pd

from scripts import build_apify_batch8_curves as batch8


def test_batch8_builder_uses_complete_tracked_evidence_without_staging_csv():
    assert batch8.RETAIL_PATHS
    assert all(path.exists() for path in batch8.RETAIL_PATHS)
    assert all("quality" not in path.parts for path in batch8.RETAIL_PATHS)

    retail = batch8._load_retail()
    retail["year_numeric"] = pd.to_numeric(retail["year"], errors="coerce")
    retail["odometer_numeric"] = pd.to_numeric(retail["odometer"], errors="coerce")
    retail["price_numeric"] = pd.to_numeric(retail["price"], errors="coerce")
    lane = batch8.LANES[0]
    year_min, year_max = lane["years"]
    market = retail[
        retail["make"].fillna("").str.lower().eq(lane["make"])
        & retail["model"].fillna("").str.lower().eq(lane["model"])
        & retail["title"].fillna("").str.contains(
            lane["title_pattern"], case=False, regex=True
        )
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

    assert len(market) == 8
