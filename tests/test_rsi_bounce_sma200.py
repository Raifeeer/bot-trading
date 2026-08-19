import unittest

import pandas as pd

from strategies.rsi_bounce_sma200 import evaluate_rsi_bounce, scan_rsi_bounces


class RsiBounceSma200Tests(unittest.TestCase):
    def make_frame(self, tail=None):
        closes = [100.0 + 0.1 * index for index in range(200)]
        closes.extend(tail or [120.0, 119.0, 118.0, 117.0, 116.0, 115.0, 114.0, 113.0, 112.0, 125.0, 126.0])
        index = pd.date_range("2026-01-01 14:30", periods=len(closes), freq="1D", tz="UTC")
        return pd.DataFrame(
            {
                "open": closes,
                "high": [value + 0.2 for value in closes],
                "low": [value - 0.2 for value in closes],
                "close": closes,
                "volume": [1_000] * len(closes),
            },
            index=index,
        )

    def kwargs(self):
        return {
            "symbol": "TQQQ",
            "timeframe": "1d",
            "rsi_period": 5,
            "oversold_threshold": 30.0,
            "oversold_lookback": 5,
            "sma_fast_period": 50,
            "sma_trend_period": 200,
            "atr_period": 3,
            "require_sma_fast_above_trend": False,
            "break_buffer_atr": 0.0,
            "session_start": "00:00",
            "session_end": "23:59",
        }

    def test_confirmed_bounce_uses_next_bar_entry(self):
        signals = scan_rsi_bounces(self.make_frame(), **self.kwargs())
        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal["direction"], "bull")
        self.assertEqual(signal["status"], "confirmed")
        self.assertLess(signal["rsi"], 100.0)
        self.assertLess(signal["rsi_threshold"], 50.0)
        self.assertGreater(pd.Timestamp(signal["entry_timestamp"]), pd.Timestamp(signal["confirmation_timestamp"]))
        self.assertFalse(signal["orders_allowed"])

    def test_sma200_filter_blocks_broken_trend(self):
        frame = self.make_frame([120.0, 119.0, 118.0, 117.0, 116.0, 90.0, 91.0])
        signals = scan_rsi_bounces(frame, **self.kwargs())
        self.assertEqual(signals, [])

    def test_invalid_input_fails_closed(self):
        with self.assertRaises(ValueError):
            evaluate_rsi_bounce(pd.DataFrame({"close": [1, 2, 3]}), **self.kwargs())


if __name__ == "__main__":
    unittest.main()
