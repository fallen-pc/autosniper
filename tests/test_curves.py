import unittest

import pandas as pd

from shared.curves import interpolate_base_by_year, interpolate_price_by_km


class CurveTests(unittest.TestCase):
    def test_interpolate_price_by_km(self) -> None:
        points = [(50000, 30000), (100000, 25000), (200000, 18000)]
        estimate = interpolate_price_by_km(points, 75000)
        self.assertAlmostEqual(estimate, 27500.0)

    def test_interpolate_base_by_year(self) -> None:
        df = pd.DataFrame(
            [
                {"group_id": "demo", "anchor_year": 2018, "km_anchor": 100000, "price_median": 20000},
                {"group_id": "demo", "anchor_year": 2020, "km_anchor": 100000, "price_median": 24000},
            ]
        )
        estimate = interpolate_base_by_year(df, "demo", 2019, 100000)
        self.assertAlmostEqual(estimate, 22000.0)


if __name__ == "__main__":
    unittest.main()
