import unittest
from copy import deepcopy

from shared.top_buy import TopBuyResult, apply_top_buy_behavior, top_buy_gate_check


def _perfect_vehicle():
    return {
        "pills": {"condition": "green", "rego": "green"},
        "damage": {
            "cosmetic_panels": 0,
            "glass_present": False,
            "replacement_present": False,
            "unknown_present": False,
        },
        "curve": {"covered": True, "confidence": 0.90, "km_percentile": 0.30},
        "resale_estimate": 20000,
        "market": {
            "autotrader_median": 20100,
            "carsales_estimate": 20300,
            "listings_cluster_ok": True,
        },
        "historical": {
            "matches": [
                {"spec_match": True, "km": 48000},
                {"spec_match": True, "km": 52000},
            ]
        },
        "odometer_reading": 50000,
        "ai_sanity": {"status": "PASS", "new_risks": []},
        "profit_margin_pct": 25.0,
    }


def _failed_keys(result):
    return [entry.split(":")[0] for entry in result.reasons_failed]


class TestTopBuyGateCheckFullPass(unittest.TestCase):
    def test_full_pass(self):
        result = top_buy_gate_check(_perfect_vehicle())
        self.assertTrue(result.is_top_buy)
        self.assertEqual(result.reasons_failed, [])


class TestTopBuyGate1(unittest.TestCase):
    def test_g1_fail_non_green_pill(self):
        v = _perfect_vehicle()
        v["pills"]["condition"] = "red"
        result = top_buy_gate_check(v)
        self.assertFalse(result.is_top_buy)
        self.assertTrue(any("G1_PILLS_NOT_ALL_GREEN" in f for f in result.reasons_failed))

    def test_g1_fail_cosmetic_damage(self):
        v = _perfect_vehicle()
        v["damage"]["cosmetic_panels"] = 2
        result = top_buy_gate_check(v)
        self.assertFalse(result.is_top_buy)
        self.assertTrue(any("G1_COSMETIC_PRESENT" in f for f in result.reasons_failed))

    def test_g1_fail_missing_pills(self):
        v = _perfect_vehicle()
        v["pills"] = {}
        result = top_buy_gate_check(v)
        self.assertFalse(result.is_top_buy)
        self.assertIn("G1_PILLS_MISSING", result.reasons_failed)


class TestTopBuyGate2(unittest.TestCase):
    def test_g2_fail_high_km(self):
        v = _perfect_vehicle()
        v["curve"]["km_percentile"] = 0.60
        result = top_buy_gate_check(v)
        self.assertFalse(result.is_top_buy)
        self.assertTrue(any("G2_LOW_KM_FAIL" in f for f in result.reasons_failed))


class TestTopBuyGate3(unittest.TestCase):
    def test_g3_fail_low_curve_confidence(self):
        v = _perfect_vehicle()
        v["curve"]["confidence"] = 0.70
        result = top_buy_gate_check(v)
        self.assertFalse(result.is_top_buy)
        self.assertTrue(any("G3_CURVE_CONF_LOW" in f for f in result.reasons_failed))


class TestTopBuyGate4(unittest.TestCase):
    def test_g4_fail_insufficient_matches(self):
        v = _perfect_vehicle()
        v["historical"]["matches"] = [{"spec_match": True, "km": 50000}]
        result = top_buy_gate_check(v)
        self.assertFalse(result.is_top_buy)
        self.assertTrue(any("G4_HIST_MATCH_COUNT_FAIL" in f for f in result.reasons_failed))


class TestTopBuyGate5(unittest.TestCase):
    def test_g5_fail_autotrader_misaligned(self):
        v = _perfect_vehicle()
        v["market"]["autotrader_median"] = 25000
        result = top_buy_gate_check(v)
        self.assertFalse(result.is_top_buy)
        self.assertTrue(any("G5_AUTOTRADER_ALIGN_FAIL" in f for f in result.reasons_failed))


class TestTopBuyGate6(unittest.TestCase):
    def test_g6_fail_ai_sanity(self):
        v = _perfect_vehicle()
        v["ai_sanity"]["status"] = "FAIL"
        result = top_buy_gate_check(v)
        self.assertFalse(result.is_top_buy)
        self.assertTrue(any("G6_AI_SANITY_FAIL" in f for f in result.reasons_failed))


class TestTopBuyGate7(unittest.TestCase):
    def test_g7_fail_low_margin(self):
        v = _perfect_vehicle()
        v["profit_margin_pct"] = 10.0
        result = top_buy_gate_check(v)
        self.assertFalse(result.is_top_buy)
        self.assertTrue(any("G7_MARGIN_TOO_LOW" in f for f in result.reasons_failed))


class TestApplyTopBuyBehavior(unittest.TestCase):
    def _passing_result(self):
        return TopBuyResult(is_top_buy=True, reasons_failed=[], reasons_passed=["all"])

    def _failing_result(self):
        return TopBuyResult(is_top_buy=False, reasons_failed=["G7_MARGIN_TOO_LOW: 10.0%"], reasons_passed=[])

    def test_apply_top_buy_uses_small_buffer(self):
        bid, badge = apply_top_buy_behavior(
            base_max_bid=10000,
            top_buy=self._passing_result(),
            standard_uncertainty_buffer=1000,
            top_buy_uncertainty_buffer=400,
        )
        self.assertEqual(bid, 9600)
        self.assertEqual(badge, "TOP BUY")

    def test_apply_standard_uses_large_buffer(self):
        bid, badge = apply_top_buy_behavior(
            base_max_bid=10000,
            top_buy=self._failing_result(),
            standard_uncertainty_buffer=1000,
        )
        self.assertEqual(bid, 9000)
        self.assertEqual(badge, "")

    def test_apply_clamps_at_zero(self):
        bid, badge = apply_top_buy_behavior(
            base_max_bid=500,
            top_buy=self._failing_result(),
            standard_uncertainty_buffer=1000,
        )
        self.assertEqual(bid, 0)
        self.assertEqual(badge, "")


if __name__ == "__main__":
    unittest.main()
