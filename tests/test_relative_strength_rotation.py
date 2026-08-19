import unittest

import pandas as pd

from strategies.relative_strength_rotation import evaluate_relative_strength


class RelativeStrengthRotationTests(unittest.TestCase):
    def make_frames(self):
        index = pd.date_range("2026-08-10", periods=5, freq="D", tz="UTC")
        return {
            "LEADER": pd.DataFrame({"close": [100, 102, 104, 106, 110]}, index=index),
            "MIDDLE": pd.DataFrame({"close": [100, 100, 100, 100, 100]}, index=index),
            "LAGGARD": pd.DataFrame({"close": [100, 98, 96, 94, 90]}, index=index),
        }

    def test_ranks_leader_against_equal_weight_benchmark(self):
        result = evaluate_relative_strength(
            self.make_frames(),
            horizon_bars=2,
            top_percentile=0.66,
            only_positive=True,
        )
        observations = {item["symbol"]: item for item in result["observations"]}
        self.assertEqual(observations["LEADER"]["direction"], "bull")
        self.assertEqual(observations["MIDDLE"]["direction"], "neutral")
        self.assertEqual(result["benchmark"], "equal_weight_universe")
        self.assertEqual(result["universe_size"], 3)
        self.assertFalse(observations["LEADER"]["orders_allowed"])
        self.assertFalse(observations["LEADER"]["influence_entries"])

    def test_laggard_is_observational_only_when_shorts_allowed(self):
        result = evaluate_relative_strength(
            self.make_frames(),
            horizon_bars=2,
            bottom_percentile=0.34,
            allow_shorts=True,
            only_positive=False,
        )
        observations = {item["symbol"]: item for item in result["observations"]}
        self.assertEqual(observations["LAGGARD"]["direction"], "bear")
        self.assertEqual(observations["LAGGARD"]["status"], "laggard")
        self.assertFalse(observations["LAGGARD"]["orders_allowed"])

    def test_missing_symbol_is_not_imputed(self):
        frames = self.make_frames()
        frames["MISSING"] = pd.DataFrame(columns=["close"])
        result = evaluate_relative_strength(frames, horizon_bars=2)
        missing = next(item for item in result["observations"] if item["symbol"] == "MISSING")
        self.assertEqual(missing["status"], "missing_data")
        self.assertEqual(result["universe_size"], 3)
        self.assertIn("MISSING", result["missing_symbols"])

    def test_asof_timestamp_blocks_future_rows(self):
        frames = self.make_frames()
        asof = "2026-08-12T23:59:00Z"
        before = evaluate_relative_strength(frames, horizon_bars=1, asof_timestamp=asof)
        frames["LEADER"].loc[pd.Timestamp("2026-08-13", tz="UTC")] = 1_000
        after = evaluate_relative_strength(frames, horizon_bars=1, asof_timestamp=asof)
        before_leader = next(item for item in before["observations"] if item["symbol"] == "LEADER")
        after_leader = next(item for item in after["observations"] if item["symbol"] == "LEADER")
        self.assertEqual(before_leader["return_formation"], after_leader["return_formation"])
        self.assertEqual(before["asof_timestamp"], after["asof_timestamp"])
