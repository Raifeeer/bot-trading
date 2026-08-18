import unittest
from datetime import date

import pandas as pd

from bot import _vix_shadow_snapshot
from strategies.vix_shadow import evaluate_vix_shadow


class FakeFeed:
    provider = "fake-real-feed"

    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def history(self, symbols, timeframe, days):
        self.calls.append((symbols, timeframe, days))
        return {"^VIX": self.frame}


class VixShadowTests(unittest.TestCase):
    def setUp(self):
        idx = pd.to_datetime(["2026-08-14", "2026-08-15", "2026-08-18"], utc=True)
        self.frame = pd.DataFrame(
            {"close": [18.0, 25.0, 40.0]}, index=idx)
        self.cfg = {
            "enabled": True,
            "mode": "shadow",
            "influence_entries": True,
            "orders_allowed": True,
            "source_symbol": "^VIX",
            "variants": ["shock_10", "level_25"],
            "history_days": 400,
        }

    def test_uses_strict_prior_exchange_close(self):
        feed = FakeFeed(self.frame)
        snapshot = evaluate_vix_shadow(
            feed, ["AMD", "TSLA"], self.cfg, as_of=date(2026, 8, 18))
        self.assertEqual(snapshot["prior_observation_date"], "2026-08-15")
        self.assertEqual(snapshot["vix"], 25.0)
        self.assertTrue(snapshot["variants"]["level_25"]["would_block"])
        self.assertEqual(snapshot["source_provider"], "fake-real-feed")

    def test_forces_operational_neutrality(self):
        snapshot = evaluate_vix_shadow(
            FakeFeed(self.frame), ["AMD"], self.cfg, as_of="2026-08-18")
        self.assertEqual(snapshot["mode"], "shadow")
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])
        self.assertTrue(snapshot["symbols"]["AMD"]["observational_only"])
        self.assertIn("risk_authority", snapshot)

    def test_missing_history_is_observable_not_authoritative(self):
        empty = FakeFeed(pd.DataFrame(columns=["close"]))
        snapshot = evaluate_vix_shadow(
            empty, ["AMD"], self.cfg, as_of="2026-08-18")
        self.assertFalse(snapshot["available"])
        self.assertEqual(snapshot["variants"]["shock_10"]["reason"], "vix_prior_close_missing")
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])

    def test_bot_wrapper_forces_neutrality(self):
        cfg = {**self.cfg, "influence_entries": True, "orders_allowed": True}
        snapshot = _vix_shadow_snapshot(FakeFeed(self.frame), ["AMD"], cfg)
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])

    def test_disabled_does_not_authorize_anything(self):
        cfg = {**self.cfg, "enabled": False}
        snapshot = evaluate_vix_shadow(
            FakeFeed(self.frame), ["AMD"], cfg, as_of="2026-08-18")
        self.assertFalse(snapshot["enabled"])
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])


if __name__ == "__main__":
    unittest.main()
