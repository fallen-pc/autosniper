import unittest

import pandas as pd

import shared.curves as curves
from shared.curves import interpolate_base_by_year, interpolate_price_by_km


class CurveTests(unittest.TestCase):
    def test_interpolate_price_by_km(self) -> None:
        points = [(50000, 30000), (100000, 25000), (200000, 18000)]
        estimate = interpolate_price_by_km(points, 75000)
        self.assertAlmostEqual(estimate, 27500.0)

    def test_interpolate_base_by_year(self) -> None:
        df = pd.DataFrame(
            [
                {"canonical_tag": "demo", "anchor_year": 2018, "km_bucket": 100000, "price_mid": 20000},
                {"canonical_tag": "demo", "anchor_year": 2020, "km_bucket": 100000, "price_mid": 24000},
            ]
        )
        estimate = interpolate_base_by_year(df, "demo", 2019, 100000)
        self.assertAlmostEqual(estimate, 22000.0)


if __name__ == "__main__":
    unittest.main()


def test_interpolate_base_by_year_resolves_curve_alias(monkeypatch, tmp_path):
    alias_path = tmp_path / "curve_aliases.csv"
    alias_path.write_text(
        "canonical_tag,base_curve\n"
        "alias_tag,base_tag\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(curves, "CURVE_ALIASES_PATH", alias_path)
    curves.load_curve_aliases.cache_clear()

    df = pd.DataFrame(
        [
            {"canonical_tag": "base_tag", "anchor_year": 2018, "km_bucket": 100000, "price_mid": 20000},
            {"canonical_tag": "base_tag", "anchor_year": 2020, "km_bucket": 100000, "price_mid": 24000},
        ]
    )

    estimate = curves.interpolate_base_by_year(df, "alias_tag", 2019, 100000)

    assert estimate == 22000.0
    curves.load_curve_aliases.cache_clear()
