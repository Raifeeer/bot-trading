import unittest

import pandas as pd

from strategies.breakout_20_55_volume import evaluate_breakout, scan_breakouts


class Breakout2055VolumeTests(unittest.TestCase):
    def make_frame(self, volume=1_000):
        closes = [100.0 + 0.05 * index for index in range(40)]
        closes.extend([102.0, 102.2, 103.5, 104.0])
        index = pd.date_range("2026-08-01 13:30", periods=len(closes), freq="5min", tz="UTC")
        return pd.DataFrame(
            {
                "open": closes,
                "high": [value + 0.2 for value in closes],
                "low": [value - 0.2 for value in closes],
                "close": closes,
                "volume": [volume] * len(closes),
            },
            index=index,
        )

    def kwargs(self):
        return {
            "symbol": "TQQQ",
            "timeframe": "5min",
            "lookback": 20,
            "volume_lookback": 5,
            "volume_min": 1.0,
            "atr_period": 5,
            "break_buffer_atr": 0.0,
            "session_start": "09:30",
            "session_end": "23:59",
        }

    def test_breakout_uses_prior_channel_and_next_open(self):
        frame = self.make_frame()
        signals = scan_breakouts(frame, **self.kwargs())
        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal["status"], "confirmed")
        self.assertEqual(signal["direction"], "bull")
        self.assertGreater(signal["close"], signal["channel_high"])
        self.assertGreater(pd.Timestamp(signal["entry_timestamp"]), pd.Timestamp(signal["confirmation_timestamp"]))
        self.assertFalse(signal["orders_allowed"])

    def test_volume_gate_blocks_low_volume_breakout(self):
        frame = self.make_frame(volume=100)
        signals = scan_breakouts(frame, **{**self.kwargs(), "volume_min": 1.2})
        self.assertEqual(signals, [])

    def test_short_request_is_fail_closed(self):
        with self.assertRaises(ValueError):
            evaluate_breakout(self.make_frame(), **{**self.kwargs(), "allow_shorts": True})


if __name__ == "__main__":
    unittest.main()
