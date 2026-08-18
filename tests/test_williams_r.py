import unittest

import pandas as pd

from strategies.williams_r import crosses_above, crosses_below, williams_r


class WilliamsRTests(unittest.TestCase):
    def test_range_and_formula(self):
        frame = pd.DataFrame({"high": [10.0, 11.0, 12.0],
                              "low": [0.0, 0.0, 0.0],
                              "close": [5.0, 8.0, 9.0]})
        result = williams_r(frame, period=3)
        self.assertAlmostEqual(float(result.iloc[-1]), -25.0)
        self.assertGreaterEqual(float(result.iloc[-1]), -100.0)
        self.assertLessEqual(float(result.iloc[-1]), 0.0)

    def test_zero_range_is_nan(self):
        frame = pd.DataFrame({"high": [10.0, 10.0, 10.0],
                              "low": [10.0, 10.0, 10.0],
                              "close": [10.0, 10.0, 10.0]})
        self.assertTrue(pd.isna(williams_r(frame, period=3).iloc[-1]))

    def test_crosses_use_previous_closed_bar(self):
        values = pd.Series([-90.0, -70.0, -40.0, -60.0])
        self.assertTrue(bool(crosses_above(values, -50.0).iloc[2]))
        self.assertTrue(bool(crosses_below(values, -50.0).iloc[3]))
        self.assertFalse(bool(crosses_above(values, -50.0).iloc[1]))


if __name__ == "__main__":
    unittest.main()
