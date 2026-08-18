import unittest

import numpy as np
import pandas as pd

from strategies.smc_expanded import confirmed_swings, fair_value_gaps, snapshot


class SMCExpandedTests(unittest.TestCase):
    def _frame(self, n=80):
        idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
        close = np.linspace(100.0, 110.0, n)
        return pd.DataFrame({"open": close - 0.1, "high": close + 0.2,
                             "low": close - 0.2, "close": close,
                             "volume": np.full(n, 1000.0)}, index=idx)

    def test_insufficient_history_is_neutral(self):
        frame = self._frame(20)
        result = snapshot(frame)
        self.assertFalse(result["coverage"])
        self.assertEqual(result["bias"], "neutral")

    def test_fvg_is_confirmed_after_third_bar(self):
        frame = self._frame(80)
        frame.iloc[50, frame.columns.get_loc("high")] = 100.0
        frame.iloc[50, frame.columns.get_loc("low")] = 99.5
        frame.iloc[51, frame.columns.get_loc("open")] = 100.2
        frame.iloc[51, frame.columns.get_loc("close")] = 103.0
        frame.iloc[51, frame.columns.get_loc("low")] = 100.2
        frame.iloc[52, frame.columns.get_loc("low")] = 103.5
        frame.iloc[52, frame.columns.get_loc("close")] = 104.0
        gaps = fair_value_gaps(frame, max_age_bars=40)
        self.assertTrue(any(g.direction == "bull" for g in gaps))

    def test_confirmed_swings_do_not_use_last_order_bars(self):
        frame = self._frame(30)
        frame.iloc[-1, frame.columns.get_loc("high")] = 1000.0
        swings = confirmed_swings(frame, order=3)
        self.assertTrue(all(idx <= len(frame) - 4 for idx, _, _ in swings))


if __name__ == "__main__":
    unittest.main()
