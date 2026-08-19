import unittest

import pandas as pd

from bot import _trend_pullback_shadow_snapshot


class TrendPullbackShadowTests(unittest.TestCase):
    def setUp(self):
        index = pd.date_range("2026-08-18 13:30", periods=40, freq="5min", tz="UTC")
        closes = [100 + min(i, 8) for i in range(40)]
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
            "ema_fast": 3,
            "ema_slow": 5,
            "atr_period": 3,
            "trend_slope_bars": 1,
            "impulse_lookback": 3,
            "pullback_lookback": 3,
            "volume_lookback": 3,
            "require_vwap_alignment": False,
            "require_volume": False,
        }

    def test_wrapper_forces_shadow_neutrality(self):
        snapshot = _trend_pullback_shadow_snapshot(
            {"15min": {"AMD": self.frame}}, ["AMD"], self.cfg)
        self.assertEqual(snapshot["mode"], "shadow")
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])
        self.assertTrue(snapshot["symbols"]["AMD"]["observational_only"])
        self.assertEqual(snapshot["risk_authority"], "risk_manager_only")

    def test_missing_data_is_observable_and_fail_closed(self):
        snapshot = _trend_pullback_shadow_snapshot(
            {"15min": {"AMD": self.frame}}, ["AMD", "TSLA"], self.cfg)
        self.assertEqual(snapshot["symbols"]["TSLA"]["status"], "missing_data")
        self.assertEqual(snapshot["counts"]["missing_data"], 1)
        self.assertFalse(snapshot["symbols"]["TSLA"]["orders_allowed"])

    def test_disabled_layer_stays_non_authoritative(self):
        snapshot = _trend_pullback_shadow_snapshot(
            {"15min": {"AMD": self.frame}}, ["AMD"], {**self.cfg, "enabled": False})
        self.assertFalse(snapshot["enabled"])
        self.assertEqual(snapshot["mode"], "disabled")
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])


if __name__ == "__main__":
    unittest.main()
