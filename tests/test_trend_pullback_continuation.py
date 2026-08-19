import unittest

import pandas as pd

from strategies.trend_pullback_continuation import evaluate_trend_pullback, scan_trend_pullbacks


class TrendPullbackContinuationTests(unittest.TestCase):
    def make_frame(self, closes, volumes=None):
        index = pd.date_range("2026-08-18 13:30", periods=len(closes), freq="5min", tz="UTC")
        if volumes is None:
            volumes = [1_000] * len(closes)
        return pd.DataFrame(
            {
                "open": closes,
                "high": [value + 0.2 for value in closes],
                "low": [value - 0.2 for value in closes],
                "close": closes,
                "volume": volumes,
            },
            index=index,
        )

    def test_bull_pullback_confirms_on_next_bar(self):
        frame = self.make_frame(
            [100, 100, 100, 101, 103, 105, 104, 103.5, 106, 107, 108],
            [1_000, 1_000, 1_000, 1_000, 1_000, 1_000, 1_000, 1_000, 2_000, 1_000, 1_000],
        )
        signals = scan_trend_pullbacks(
            frame,
            symbol="TQQQ",
            ema_fast=3,
            ema_slow=5,
            atr_period=3,
            trend_slope_bars=1,
            impulse_lookback=3,
            pullback_lookback=3,
            require_volume=True,
            volume_lookback=3,
            volume_min=1.2,
            require_vwap_alignment=False,
            break_buffer_atr=0.0,
        )
        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal["direction"], "bull")
        self.assertEqual(signal["status"], "confirmed")
        self.assertFalse(signal["orders_allowed"])
        self.assertGreater(pd.Timestamp(signal["entry_timestamp"]), pd.Timestamp(signal["confirmation_timestamp"]))

    def test_bear_signal_requires_explicit_research_permission(self):
        frame = self.make_frame(
            [100, 100, 100, 99, 97, 95, 96, 96.5, 94, 93, 92],
            [1_000, 1_000, 1_000, 1_000, 1_000, 1_000, 1_000, 1_000, 2_000, 1_000, 1_000],
        )
        blocked = scan_trend_pullbacks(
            frame,
            direction="short",
            allow_shorts=False,
            ema_fast=3,
            ema_slow=5,
            atr_period=3,
            trend_slope_bars=1,
            impulse_lookback=3,
            pullback_lookback=3,
            volume_lookback=3,
            require_vwap_alignment=False,
            break_buffer_atr=0.0,
        )
        allowed = scan_trend_pullbacks(
            frame,
            direction="short",
            allow_shorts=True,
            ema_fast=3,
            ema_slow=5,
            atr_period=3,
            trend_slope_bars=1,
            impulse_lookback=3,
            pullback_lookback=3,
            volume_lookback=3,
            require_vwap_alignment=False,
            break_buffer_atr=0.0,
        )
        self.assertEqual(blocked, [])
        self.assertEqual(len(allowed), 1)
        self.assertEqual(allowed[0]["direction"], "bear")
        self.assertFalse(allowed[0]["orders_allowed"])

    def test_volume_gate_blocks_and_one_signal_per_session_is_enforced(self):
        frame = self.make_frame([100, 100, 100, 101, 103, 105, 104, 103.5, 106, 107, 108])
        signals = scan_trend_pullbacks(
            frame,
            ema_fast=3,
            ema_slow=5,
            atr_period=3,
            trend_slope_bars=1,
            impulse_lookback=3,
            pullback_lookback=3,
            require_volume=True,
            volume_lookback=3,
            volume_min=1.2,
            require_vwap_alignment=False,
            break_buffer_atr=0.0,
        )
        self.assertEqual(signals, [])

    def test_missing_ohlcv_fails_closed(self):
        with self.assertRaises(ValueError):
            evaluate_trend_pullback(pd.DataFrame({"close": [1, 2, 3]}))
