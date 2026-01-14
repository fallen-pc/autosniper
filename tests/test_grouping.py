import unittest

from shared.grouping import assign_group_id


class GroupingTests(unittest.TestCase):
    def test_hilux_sr5_dualcab_4x4(self) -> None:
        row = {
            "make": "Toyota",
            "model": "Hilux",
            "variant": "SR5 4x4 Dual Cab",
            "body_type": "Dual Cab Ute",
            "fuel_type": "Diesel",
            "transmission": "Automatic",
            "engine_capacity": "2.8L",
            "location": "Melbourne VIC",
        }
        group_id, reason = assign_group_id(row)
        self.assertEqual(group_id, "toyota_hilux_dualcab_ute_diesel_auto_sr5_4x4")
        self.assertEqual(reason, "")

    def test_hilux_hirider_excluded(self) -> None:
        row = {
            "make": "Toyota",
            "model": "Hilux",
            "variant": "SR5 Hi-Rider 4x2",
            "body_type": "Dual Cab Ute",
            "fuel_type": "Diesel",
            "transmission": "Automatic",
            "engine_capacity": "2.8L",
            "location": "VIC",
        }
        group_id, reason = assign_group_id(row)
        self.assertIsNone(group_id)
        self.assertIn("DRIVETRAIN_MISMATCH", reason)

    def test_golf_gti_excluded(self) -> None:
        row = {
            "make": "Volkswagen",
            "model": "Golf",
            "variant": "GTI",
            "body_type": "Hatchback",
            "fuel_type": "Petrol",
            "transmission": "Automatic",
            "location": "VIC",
        }
        group_id, reason = assign_group_id(row)
        self.assertIsNone(group_id)
        self.assertIn("PERFORMANCE_TRIM", reason)

    def test_corolla_pre_2013_excluded(self) -> None:
        row = {
            "year": 2010,
            "make": "Toyota",
            "model": "Corolla",
            "variant": "Ascent ZRE152R",
            "body_type": "Hatchback",
            "fuel_type": "Petrol",
            "transmission": "Automatic",
            "location": "VIC",
        }
        group_id, reason = assign_group_id(row)
        self.assertIsNone(group_id)
        self.assertIn("GENERATION_NOT_MODELED", reason)


if __name__ == "__main__":
    unittest.main()
