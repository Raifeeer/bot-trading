import unittest

import pandas as pd

from strategies.relative_strength_priority import evaluate_priority


class RelativeStrengthPriorityTests(unittest.TestCase):
    def frames(self):
        index = pd.date_range("2026-08-01", periods=80, freq="D", tz="UTC")
        return {
            "AMD": pd.DataFrame({"close": [100 + index * 0.5 for index in range(80)]}, index=index),
            "F": pd.DataFrame({"close": [100 + index * 0.1 for index in range(80)]}, index=index),
            "BB": pd.DataFrame({"close": [100 - index * 0.2 for index in range(80)]}, index=index),
        }

    def test_leader_is_priority_candidate_asof(self):
        result = evaluate_priority(self.frames(), horizon_bars=20, top_k=1, gate="bull", current_regime="bull", asof_timestamp="2026-10-01T00:00:00Z")
        self.assertEqual(result["leader_symbols"], ["AMD"])
        amd = next(observation for observation in result["observations"] if observation["symbol"] == "AMD")
        self.assertTrue(amd["priority_candidate"])
        self.assertTrue(amd["would_pass_overlay"])

    def test_bear_regime_blocks_overlay_without_changing_rank(self):
        result = evaluate_priority(self.frames(), horizon_bars=20, top_k=1, gate="bull", current_regime="bear", asof_timestamp="2026-10-01T00:00:00Z")
        self.assertEqual(result["leader_symbols"], ["AMD"])
        amd = next(observation for observation in result["observations"] if observation["symbol"] == "AMD")
        self.assertTrue(amd["priority_candidate"])
        self.assertFalse(amd["would_pass_overlay"])
        self.assertFalse(result["orders_allowed"])

    def test_missing_symbol_is_fail_closed(self):
        frames = self.frames()
        frames["TSLA"] = pd.DataFrame(columns=["close"])
        result = evaluate_priority(frames, horizon_bars=20, top_k=1, gate="none", current_regime="bull", asof_timestamp="2026-10-01T00:00:00Z")
        tsla = next(observation for observation in result["observations"] if observation["symbol"] == "TSLA")
        self.assertFalse(tsla["priority_candidate"])
        self.assertFalse(tsla["would_pass_overlay"])


if __name__ == "__main__":
    unittest.main()
