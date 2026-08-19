import unittest

import pandas as pd

from bot import _bearish_breakdown_shadow_snapshot


class BearishBreakdownShadowTests(unittest.TestCase):
    def setUp(self):
        index = pd.date_range("2026-08-17 13:30", periods=50, freq="15min", tz="UTC")
        self.frame = pd.DataFrame(
            {
                "open": [100.0] * 50,
                "high": [100.5] * 50,
                "low": [99.5] * 50,
                "close": [100.0] * 50,
                "volume": [1_000.0] * 50,
            },
            index=index,
        )
        self.cfg = {
            "enabled": True,
            "mode": "paper_filter",
            "influence_entries": True,
            "orders_allowed": True,
            "timeframe": "15min",
            "lookback": 20,
            "volume_min": 1.2,
            "retest_max_bars": 3,
        }

    def test_wrapper_forces_shadow_neutrality(self):
        snapshot = _bearish_breakdown_shadow_snapshot(
            {"15min": {"AMD": self.frame}}, ["AMD"], self.cfg)
        self.assertEqual(snapshot["mode"], "shadow")
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])
        self.assertEqual(snapshot["symbols"]["AMD"]["status"], "no_setup")
        self.assertTrue(snapshot["symbols"]["AMD"]["observational_only"])
        self.assertEqual(snapshot["counts"]["no_setup"], 1)

    def test_missing_symbol_is_observable_not_authoritative(self):
        snapshot = _bearish_breakdown_shadow_snapshot(
            {"15min": {}}, ["SOFI"], self.cfg)
        observation = snapshot["symbols"]["SOFI"]
        self.assertEqual(observation["status"], "missing_data")
        self.assertFalse(observation["orders_allowed"])
        self.assertFalse(observation["influence_entries"])
        self.assertEqual(snapshot["counts"]["missing_data"], 1)

    def test_disabled_layer_cannot_authorize_orders(self):
        snapshot = _bearish_breakdown_shadow_snapshot(
            {"15min": {"AMD": self.frame}}, ["AMD"], {**self.cfg, "enabled": False})
        self.assertFalse(snapshot["enabled"])
        self.assertEqual(snapshot["mode"], "disabled")
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])


if __name__ == "__main__":
    unittest.main()
