import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot import _entry_context_key, _latest_bar_key  # noqa: E402


class SchedulerContextTests(unittest.TestCase):
    def setUp(self):
        idx = pd.date_range("2026-08-17 15:30", periods=3, freq="5min", tz="UTC")
        self.data = {"AAA": pd.DataFrame({"close": [1.0, 1.1, 1.2]}, index=idx)}

    def test_latest_bar_key_is_stable_for_same_dataset(self):
        self.assertEqual(
            _latest_bar_key(self.data), "2026-08-17 15:40:00+00:00"
        )
        self.assertEqual(_entry_context_key(self.data, {"regime": "bull"}),
                         "2026-08-17 15:40:00+00:00|bull|floor=False")

    def test_new_bar_changes_context(self):
        first = _entry_context_key(self.data, {"regime": "bull"})
        idx = pd.date_range("2026-08-17 15:30", periods=4, freq="5min", tz="UTC")
        newer = {"AAA": pd.DataFrame({"close": [1.0, 1.1, 1.2, 1.3]}, index=idx)}
        self.assertNotEqual(first, _entry_context_key(newer, {"regime": "bull"}))

    def test_regime_or_floor_change_changes_context(self):
        bull = _entry_context_key(self.data, {"regime": "bull", "floor": {"below_floor": False}})
        bear = _entry_context_key(self.data, {"regime": "bear", "floor": {"below_floor": False}})
        below = _entry_context_key(self.data, {"regime": "bull", "floor": {"below_floor": True}})
        self.assertNotEqual(bull, bear)
        self.assertNotEqual(bull, below)


if __name__ == "__main__":
    unittest.main()
