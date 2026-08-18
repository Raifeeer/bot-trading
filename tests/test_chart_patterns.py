import unittest

import pandas as pd

from strategies.chart_patterns import detect_all, double_bottom


class ChartPatternTests(unittest.TestCase):
    def test_insufficient_data_is_neutral(self):
        index = pd.date_range("2026-01-01", periods=10, freq="15min", tz="UTC")
        frame = pd.DataFrame({"open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0,
                             "volume": 1000.0}, index=index)
        detected = detect_all(frame)
        self.assertFalse(detected["double_bottom"].any())
        self.assertFalse((detected["triangle"] != 0).any())

    def test_double_bottom_needs_breakout(self):
        index = pd.date_range("2026-01-01", periods=45, freq="15min", tz="UTC")
        close = [10.0] * 45
        low = [value - 0.2 for value in close]
        high = [value + 0.2 for value in close]
        for i in (8, 20):
            close[i] = 8.0
            low[i] = 7.8
            high[i] = 8.2
        close[14] = 9.5
        high[14] = 10.8
        for i in range(30, 45):
            close[i] = 11.0
            high[i] = 11.3
        frame = pd.DataFrame({"open": close, "high": high, "low": low,
                             "close": close, "volume": 1000.0}, index=index)
        result = double_bottom(frame)
        self.assertTrue(result.any())
        self.assertGreaterEqual(result[result].index[0], index[20])


if __name__ == "__main__":
    unittest.main()
