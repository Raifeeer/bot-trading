import unittest

import pandas as pd

from strategies.vix_filter import blocked_by_vix, daily_features, prior_close_for_date


class VixFilterTests(unittest.TestCase):
    def test_prior_close_is_strictly_before_trade_date(self):
        idx = pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True)
        features = daily_features(pd.Series([15.0, 30.0], index=idx))
        row = prior_close_for_date(features, pd.Timestamp("2026-01-02").date())
        self.assertAlmostEqual(float(row["vix"]), 15.0)

    def test_missing_vix_blocks_nonbaseline(self):
        self.assertTrue(blocked_by_vix(None, "level_25"))
        self.assertFalse(blocked_by_vix(None, "baseline"))

    def test_shock_feature_uses_previous_observation(self):
        idx = pd.date_range("2026-01-01", periods=22, freq="D", tz="UTC")
        values = pd.Series([15.0] * 21 + [20.0], index=idx)
        features = daily_features(values)
        self.assertTrue(blocked_by_vix(features.iloc[-1], "shock_20"))


if __name__ == "__main__":
    unittest.main()
