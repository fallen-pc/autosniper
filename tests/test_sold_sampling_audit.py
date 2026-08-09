from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.sold_sampling_audit import build_report, build_sample, summarize_report


def _write_sold(path: Path, n: int) -> None:
    pd.DataFrame(
        {
            "url": [f"https://grays.com/lot/{i}" for i in range(n)],
            "price": [1000 + i for i in range(n)],
            "year": 2015,
            "make": "toyota",
            "model": "corolla",
            "variant": "ascent",
        }
    ).to_csv(path, index=False)


def test_build_sample_excludes_already_rescraped_and_stratifies(tmp_path) -> None:
    source = tmp_path / "sold.csv"
    _write_sold(source, 250)
    rescraped = tmp_path / "rescraped.csv"
    # newest 50 rows (bottom of file) already verified
    pd.DataFrame({"url": [f"https://grays.com/lot/{i}" for i in range(200, 250)]}).to_csv(
        rescraped, index=False
    )

    sample = build_sample(source, rescraped, per_band=10, band_size=100, seed=1)

    assert not sample["url"].isin([f"https://grays.com/lot/{i}" for i in range(200, 250)]).any()
    # 250 rows -> bands 0,100,200 by source_from_end; band 0 is newest and fully rescraped-excluded but not empty (rows 150-199 remain)
    per_band = sample.groupby("band").size()
    assert (per_band <= 10).all()
    assert len(per_band) >= 2
    # deterministic under the same seed
    again = build_sample(source, rescraped, per_band=10, band_size=100, seed=1)
    assert sample["url"].tolist() == again["url"].tolist()


def test_report_flags_mismatched_band(tmp_path) -> None:
    sample = tmp_path / "sample.csv"
    pd.DataFrame(
        {
            "url": [f"https://grays.com/lot/{i}" for i in range(20)],
            "price": [1000] * 20,
            "source_from_end": list(range(20)),
            "band": [0] * 10 + [100] * 10,
        }
    ).to_csv(sample, index=False)

    rescrape = tmp_path / "rescrape.csv"
    # band 0 rescrapes clean; band 100 comes back with different prices
    pd.DataFrame(
        {
            "url": [f"https://grays.com/lot/{i}" for i in range(20)],
            "price": [1000] * 10 + [9000] * 10,
        }
    ).to_csv(rescrape, index=False)

    detail = build_report(sample, rescrape)
    summary = summarize_report(detail)

    band0 = summary[summary["band"] == 0].iloc[0]
    band100 = summary[summary["band"] == 100].iloc[0]
    assert band0["mismatches"] == 0
    assert band0["verdict"] == "CLEAN"
    assert band0["clean_upper_bound_95"] == 3.0 / 10
    assert band100["mismatches"] == 10
    assert band100["verdict"] == "SUSPECT"


def test_report_missing_rescrape_rows_counted_but_not_mismatched(tmp_path) -> None:
    sample = tmp_path / "sample.csv"
    pd.DataFrame(
        {
            "url": ["https://grays.com/lot/1", "https://grays.com/lot/2"],
            "price": [1000, 2000],
            "source_from_end": [0, 1],
            "band": [0, 0],
        }
    ).to_csv(sample, index=False)

    rescrape = tmp_path / "rescrape.csv"
    pd.DataFrame({"url": ["https://grays.com/lot/1"], "price": [1000]}).to_csv(rescrape, index=False)

    detail = build_report(sample, rescrape)
    assert detail["rescraped"].sum() == 1
    assert detail["mismatch"].sum() == 0
    summary = summarize_report(detail)
    assert summary.iloc[0]["verdict"] == "INSUFFICIENT"  # only 1 rescraped < 10
