import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.feed import MarketDataFeed


class TestMarketDataFeedCache(unittest.TestCase):
    def test_superset_history_is_reused_and_trimmed(self):
        feed = MarketDataFeed("alpaca")
        calls = []
        base_end = pd.Timestamp(datetime.now(timezone.utc)).floor("D")
        frame = pd.DataFrame(
            {
                "open": range(500),
                "high": range(500),
                "low": range(500),
                "close": range(500),
                "volume": range(500),
            },
            index=pd.date_range(end=base_end, periods=500, freq="D", tz="UTC"),
        )

        def fake_bars(symbol, timeframe, start, end=None, force=False):
            calls.append((symbol, timeframe, start, end))
            return frame.copy()

        feed.bars = fake_bars
        first = feed.history(["SOFI"], "1d", days=400)
        second = feed.history(["SOFI"], "1d", days=100)

        self.assertEqual(len(calls), 1)
        self.assertIn("SOFI", first)
        self.assertIn("SOFI", second)
        self.assertLessEqual(len(second["SOFI"]), 101)


if __name__ == "__main__":
    unittest.main()
