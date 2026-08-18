import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategies.setup_confluence import SETUP_NAMES, analyze_setup_confluence


class SetupConfluenceTests(unittest.TestCase):
    def _frame(self, n=100):
        idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
        close = np.linspace(100.0, 112.0, n)
        close[-8:] = [110.0, 109.8, 110.2, 111.0, 110.5, 111.2, 112.0, 112.4]
        high = close + 0.4
        low = close - 0.4
        open_ = close - 0.1
        volume = np.linspace(1000.0, 1800.0, n)
        return pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=idx,
        )

    def test_all_setups_are_returned_and_serializable(self):
        result = analyze_setup_confluence("TEST", {"5m": self._frame(), "1d": self._frame()})
        names = {item["setup"] for item in result["observations"]}
        self.assertTrue(set(SETUP_NAMES).issubset(names))
        self.assertIn("mtf_confluence", names)
        self.assertIn(result["direction"], {"bull", "bear", "neutral"})
        self.assertIsInstance(result["score"], float)
        for item in result["observations"]:
            self.assertIn(item["direction"], {"bull", "bear", "neutral"})
            self.assertIn("decision_ts", item)
            self.assertIn("evidence", item)
            self.assertIn("invalidation", item)

    def test_missing_data_is_neutral_for_every_setup(self):
        result = analyze_setup_confluence("TEST", {})
        self.assertEqual(result["direction"], "neutral")
        self.assertEqual(result["status"], "no_data")
        self.assertEqual(len(result["observations"]), len(SETUP_NAMES))
        self.assertTrue(all(item["direction"] == "neutral" for item in result["observations"]))

    def test_key_level_detects_closed_break(self):
        frame = self._frame()
        frame.iloc[-2, frame.columns.get_loc("high")] = 110.0
        frame.iloc[-2, frame.columns.get_loc("close")] = 109.5
        frame.iloc[-1, frame.columns.get_loc("high")] = 115.0
        frame.iloc[-1, frame.columns.get_loc("close")] = 114.0
        result = analyze_setup_confluence("TEST", {"1d": frame})
        key_level = next(item for item in result["observations"] if item["setup"] == "key_level")
        self.assertEqual(key_level["direction"], "bull")
        self.assertIn(key_level["status"], {"candidate", "confirmed"})

    def test_setup_does_not_emit_order_permission(self):
        result = analyze_setup_confluence("TEST", {"5m": self._frame()})
        self.assertNotIn("order", result)
        self.assertNotIn("sizing", result)
        self.assertNotIn("risk_decision", result)


if __name__ == "__main__":
    unittest.main()
