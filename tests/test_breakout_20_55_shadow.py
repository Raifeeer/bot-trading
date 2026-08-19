import unittest

import pandas as pd

from bot import _breakout_20_55_shadow_snapshot


class Breakout2055ShadowTests(unittest.TestCase):
    def setUp(self):
        index = pd.date_range("2026-08-18 13:30", periods=80, freq="5min", tz="UTC")
        closes = [100.0 + 0.05 * index for index in range(80)]
        self.frame = pd.DataFrame(
            {
                "open": closes,
                "high": [value + 0.2 for value in closes],
                "low": [value - 0.2 for value in closes],
                "close": closes,
                "volume": [1_000] * len(closes),
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
            "volume_lookback": 5,
            "volume_min": 1.0,
            "atr_period": 5,
            "gate": "bull",
            "session_start": "09:30",
            "session_end": "23:59",
        }

    def test_wrapper_forces_shadow_neutrality(self):
        snapshot = _breakout_20_55_shadow_snapshot(
            {"15min": {"AMD": self.frame}}, ["AMD"], self.cfg, {"regime": "bull"})
        self.assertEqual(snapshot["mode"], "shadow")
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])
        self.assertTrue(snapshot["symbols"]["AMD"]["observational_only"])
        self.assertEqual(snapshot["risk_authority"], "risk_manager_only")

    def test_missing_data_is_fail_closed(self):
        snapshot = _breakout_20_55_shadow_snapshot(
            {"15min": {"AMD": self.frame}}, ["AMD", "TSLA"], self.cfg, {"regime": "bear"})
        self.assertEqual(snapshot["symbols"]["TSLA"]["status"], "missing_data")
        self.assertFalse(snapshot["symbols"]["TSLA"]["orders_allowed"])
        self.assertEqual(snapshot["counts"]["gate_allowed"], 0)

    def test_disabled_layer_stays_non_authoritative(self):
        snapshot = _breakout_20_55_shadow_snapshot(
            {"15min": {"AMD": self.frame}}, ["AMD"], {**self.cfg, "enabled": False})
        self.assertFalse(snapshot["enabled"])
        self.assertEqual(snapshot["mode"], "disabled")
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])


if __name__ == "__main__":
    unittest.main()
