import unittest

import pandas as pd

from strategies.failure_retest_breakout import evaluate_failure_retest, scan_failure_retests


class FailureRetestBreakoutTests(unittest.TestCase):
    def base_frame(self):
        closes = [100.0 + 0.02 * index for index in range(40)]
        closes.extend([101.5, 101.0, 101.8, 102.4, 102.5])
        index = pd.date_range("2026-08-19 13:30", periods=len(closes), freq="5min", tz="UTC")
        return pd.DataFrame(
            {
                "open": closes,
                "high": [value + 0.3 for value in closes],
                "low": [value - 0.3 for value in closes],
                "close": closes,
                "volume": [1_000] * len(closes),
            },
            index=index,
        )

    def kwargs(self):
        return {
            "symbol": "TQQQ",
            "timeframe": "5min",
            "lookback": 20,
            "retest_max_bars": 3,
            "retest_tolerance_atr": 0.25,
            "volume_lookback": 5,
            "atr_period": 5,
            "volume_min": 0.0,
            "session_start": "09:30",
            "session_end": "23:59",
        }

    def test_acceptance_after_retest_has_next_entry(self):
        events = scan_failure_retests(self.base_frame(), **self.kwargs())
        accepted = [event for event in events if event["status"] == "accepted"]
        self.assertTrue(accepted)
        event = accepted[-1]
        self.assertIsNotNone(event["retest_timestamp"])
        self.assertGreater(pd.Timestamp(event["entry_timestamp"]), pd.Timestamp(event["decision_timestamp"]))
        self.assertFalse(event["orders_allowed"])

    def test_failed_breakout_is_observational_not_short(self):
        frame = self.base_frame()
        frame.iloc[-3, frame.columns.get_loc("close")] = 100.2
        frame.iloc[-3, frame.columns.get_loc("low")] = 99.5
        events = scan_failure_retests(frame, **self.kwargs())
        self.assertTrue(any(event["status"] == "failed" for event in events))
        self.assertTrue(all(event["direction"] == "bull" for event in events))

    def test_shorts_are_blocked_and_empty_is_fail_closed(self):
        with self.assertRaises(ValueError):
            scan_failure_retests(self.base_frame(), **{**self.kwargs(), "allow_shorts": True})
        empty = evaluate_failure_retest(pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), **self.kwargs())
        self.assertEqual(empty["status"], "no_setup")
        self.assertFalse(empty["orders_allowed"])


if __name__ == "__main__":
    unittest.main()
