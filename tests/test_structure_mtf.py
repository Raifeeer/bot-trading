import unittest

import pandas as pd

from strategies.structure_mtf import evaluate_structure_mtf, evaluate_universe_structure


def frame(high, low, close):
    index = pd.date_range("2026-01-01", periods=len(close), freq="15min", tz="UTC")
    return pd.DataFrame({
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": [100.0] * len(close),
    }, index=index)


class StructureMtfTests(unittest.TestCase):
    def test_bull_structure_requires_higher_high_and_higher_low(self):
        prices = [10, 9, 11, 10, 12, 11, 13, 12, 14, 13, 15, 14, 16]
        df = frame(prices, [p - 1 for p in prices], prices)
        obs = evaluate_structure_mtf({"1d": df, "15min": df, "5min": df}, order=1)
        self.assertEqual(obs["direction"], "bull")
        self.assertGreater(obs["score"], 0.5)
        self.assertFalse(obs["orders_allowed"])
        self.assertFalse(obs["influence_entries"])

    def test_bear_structure_requires_lower_high_and_lower_low(self):
        prices = [16, 17, 15, 16, 14, 15, 13, 14, 12, 13, 11, 12, 10]
        df = frame(prices, [p - 1 for p in prices], prices)
        obs = evaluate_structure_mtf({"1d": df, "15min": df, "5min": df}, order=1)
        self.assertEqual(obs["direction"], "bear")
        self.assertLess(obs["score"], -0.5)
        self.assertFalse(obs["orders_allowed"])

    def test_insufficient_data_is_neutral(self):
        df = frame([10, 11], [9, 10], [9.5, 10.5])
        obs = evaluate_structure_mtf({"1d": df, "15min": None, "5min": None})
        self.assertEqual(obs["direction"], "neutral")
        self.assertEqual(obs["available_weight"], 0.0)
        self.assertFalse(obs["orders_allowed"])

    def test_bot_wrapper_forces_neutrality(self):
        from bot import _structure_mtf_shadow_snapshot

        prices = [10, 9, 11, 10, 12, 11, 13, 12, 14, 13, 15, 14, 16]
        df = frame(prices, [p - 1 for p in prices], prices)
        snapshot = _structure_mtf_shadow_snapshot(
            {"1d": {"AAA": df}, "15min": {"AAA": df}, "5min": {"AAA": df}},
            ["AAA"],
            {"enabled": True, "mode": "paper_filter",
             "influence_entries": True, "orders_allowed": True},
        )
        self.assertEqual(snapshot["mode"], "shadow")
        self.assertFalse(snapshot["orders_allowed"])
        self.assertFalse(snapshot["influence_entries"])

    def test_universe_counts_are_observational(self):
        bull = [10, 9, 11, 10, 12, 11, 13, 12, 14, 13, 15, 14, 16]
        bear = [16, 17, 15, 16, 14, 15, 13, 14, 12, 13, 11, 12, 10]
        frames = {
            "AAA": {"1d": frame(bull, [p - 1 for p in bull], bull),
                    "15min": frame(bull, [p - 1 for p in bull], bull),
                    "5min": frame(bull, [p - 1 for p in bull], bull)},
            "BBB": {"1d": frame(bear, [p - 1 for p in bear], bear),
                    "15min": frame(bear, [p - 1 for p in bear], bear),
                    "5min": frame(bear, [p - 1 for p in bear], bear)},
        }
        result = evaluate_universe_structure(frames, order=1)
        self.assertEqual(result["bull_count"], 1)
        self.assertEqual(result["bear_count"], 1)
        self.assertFalse(result["orders_allowed"])
        self.assertFalse(result["influence_entries"])


if __name__ == "__main__":
    unittest.main()
