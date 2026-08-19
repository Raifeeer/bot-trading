import unittest

import pandas as pd

from strategies.vwap_reclaim_pullback import evaluate_vwap, scan_vwap


class VwapReclaimPullbackTests(unittest.TestCase):
    def frame(self, closes, highs, lows, volumes):
        index = pd.date_range(
            "2026-08-18 13:30", periods=len(closes), freq="5min", tz="UTC"
        )
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

    def test_reclaim_long_after_displacement_and_retracement(self):
        frame = self.frame(
            [100.0, 102.0, 99.5, 101.5, 101.7],
            [100.2, 102.2, 100.0, 101.7, 101.9],
            [99.8, 101.8, 99.0, 99.8, 101.4],
            [1_000, 1_000, 1_000, 2_000, 1_000],
        )
        observations = scan_vwap(
            frame,
            timeframe="5min",
            mode="reclaim",
            direction="long",
            atr_period=2,
            volume_lookback=2,
            volume_min=1.5,
            break_buffer_atr=0.0,
        )
        self.assertEqual(len(observations), 1)
        signal = observations[0]
        self.assertEqual(signal["direction"], "bull")
        self.assertTrue(signal["displacement"])
        self.assertTrue(signal["retracement"])
        self.assertFalse(signal["orders_allowed"])
        self.assertEqual(signal["mode"], "shadow")

    def test_pullback_requires_micro_break_and_vwap_slope(self):
        frame = self.frame(
            [100.0, 102.0, 99.5, 103.0, 103.2],
            [100.2, 102.2, 100.0, 103.2, 103.4],
            [99.8, 101.8, 99.0, 100.0, 102.8],
            [1_000, 1_000, 1_000, 2_000, 1_000],
        )
        observations = scan_vwap(
            frame,
            timeframe="5min",
            mode="pullback",
            direction="long",
            atr_period=2,
            volume_lookback=2,
            volume_min=1.5,
            break_buffer_atr=0.0,
            pullback_lookback=2,
        )
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["signal"], "vwap_pullback")
        self.assertGreater(observations[0]["vwap_slope"], 0.0)

    def test_volume_gate_blocks_without_confirmation_volume(self):
        frame = self.frame(
            [100.0, 102.0, 99.5, 101.5],
            [100.2, 102.2, 100.0, 101.7],
            [99.8, 101.8, 99.0, 99.8],
            [1_000, 1_000, 1_000, 1_000],
        )
        result = evaluate_vwap(
            frame,
            timeframe="5min",
            mode="reclaim",
            direction="long",
            atr_period=2,
            volume_lookback=2,
            volume_min=1.5,
        )
        self.assertEqual(result["status"], "no_setup")

    def test_missing_columns_fail_closed_at_detector_boundary(self):
        frame = pd.DataFrame(columns=["close"])
        with self.assertRaises(ValueError):
            scan_vwap(frame)
