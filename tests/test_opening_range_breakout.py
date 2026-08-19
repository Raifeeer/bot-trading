import unittest

import pandas as pd

from strategies.opening_range_breakout import evaluate_orb, scan_orb


class OpeningRangeBreakoutTests(unittest.TestCase):
    def frame(self, closes, highs=None, lows=None, volumes=None):
        index = pd.date_range("2026-08-17 13:30", periods=len(closes), freq="5min", tz="UTC")
        closes = [float(value) for value in closes]
        highs = highs or [value + 0.2 for value in closes]
        lows = lows or [value - 0.2 for value in closes]
        volumes = volumes or [1_000.0] * len(closes)
        return pd.DataFrame(
            {
                "open": closes,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            },
            index=index,
        )

    def test_confirms_long_after_thirty_minute_range(self):
        frame = self.frame(
            [100, 100, 100, 100, 100, 100, 102, 102.5, 102.2],
            highs=[100.2] * 6 + [102.2, 102.7, 102.4],
            lows=[99.8] * 6 + [101.8, 102.1, 101.9],
            volumes=[1_000] * 6 + [2_000, 2_000, 2_000],
        )
        observations = scan_orb(
            frame,
            timeframe="5min",
            opening_range_minutes=30,
            atr_period=2,
            volume_lookback=2,
            volume_min=1.5,
            break_buffer_atr=0.0,
        )
        self.assertEqual(len(observations), 1)
        signal = observations[0]
        self.assertEqual(signal["direction"], "bull")
        self.assertEqual(signal["opening_range_minutes"], 30)
        self.assertEqual(signal["opening_range_high"], 100.2)
        self.assertFalse(signal["orders_allowed"])

    def test_confirms_short_and_emits_only_once_per_session(self):
        frame = self.frame(
            [100, 100, 100, 100, 100, 100, 98, 97, 96],
            highs=[100.2] * 6 + [98.2, 97.2, 96.2],
            lows=[99.8] * 6 + [97.8, 96.8, 95.8],
            volumes=[1_000] * 6 + [2_000, 2_000, 2_000],
        )
        observations = scan_orb(
            frame,
            timeframe="5min",
            opening_range_minutes=30,
            direction="short",
            atr_period=2,
            require_volume=False,
            break_buffer_atr=0.0,
        )
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["direction"], "bear")

    def test_does_not_use_breakout_bar_to_build_range(self):
        frame = self.frame(
            [100, 100, 100, 100, 100, 100, 102],
            highs=[100.2] * 6 + [102.2],
            lows=[99.8] * 6 + [101.8],
            volumes=[1_000] * 6 + [2_000],
        )
        result = evaluate_orb(
            frame,
            timeframe="5min",
            opening_range_minutes=30,
            atr_period=2,
            require_volume=False,
            break_buffer_atr=0.0,
        )
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["opening_range_high"], 100.2)

    def test_missing_columns_fail_closed_as_neutral_wrapper_input(self):
        frame = pd.DataFrame(columns=["close"])
        with self.assertRaises(ValueError):
            scan_orb(frame)
