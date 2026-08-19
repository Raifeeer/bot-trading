import unittest

import pandas as pd

from strategies.intraday_mean_reversion import evaluate_intraday_mean_reversion, scan_intraday_mean_reversion


class IntradayMeanReversionTests(unittest.TestCase):
    def frame(self):
        values = [100.0] * 20 + [97.0, 97.5, 98.5, 99.2, 99.4, 99.6]
        index = pd.date_range("2026-08-19 13:30", periods=len(values), freq="5min", tz="UTC")
        return pd.DataFrame(
            {
                "open": values,
                "high": [value + 0.4 for value in values],
                "low": [value - 0.4 for value in values],
                "close": values,
                "volume": [1_000] * len(values),
            },
            index=index,
        )

    def test_reclaim_produces_next_bar_entry_and_target_vwap(self):
        events = scan_intraday_mean_reversion(
            self.frame(),
            symbol="TQQQ",
            timeframe="5min",
            extension_atr=1.0,
            reclaim_atr=0.5,
            gate="none",
            session_start="09:30",
            session_end="23:59",
        )
        confirmed = [event for event in events if event["status"] == "confirmed"]
        self.assertTrue(confirmed)
        event = confirmed[0]
        self.assertGreater(pd.Timestamp(event["entry_timestamp"]), pd.Timestamp(event["confirmation_timestamp"]))
        self.assertGreater(event["target_price"], event["entry"])
        self.assertFalse(event["orders_allowed"])

    def test_bull_gate_blocks_non_bull_regime(self):
        events = scan_intraday_mean_reversion(
            self.frame(),
            symbol="TQQQ",
            gate="bull",
            regime_by_session={"2026-08-19": "bear"},
            session_start="09:30",
            session_end="23:59",
        )
        self.assertEqual(events, [])

    def test_no_reclaim_and_missing_data_are_fail_closed(self):
        frame = self.frame()
        frame.iloc[-3:, frame.columns.get_loc("close")] = 97.0
        frame.iloc[-3:, frame.columns.get_loc("low")] = 96.6
        events = scan_intraday_mean_reversion(
            frame,
            symbol="TQQQ",
            gate="none",
            session_start="09:30",
            session_end="23:59",
        )
        self.assertTrue(any(event["status"] == "extension_no_reclaim" for event in events))
        empty = evaluate_intraday_mean_reversion(pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), symbol="TQQQ")
        self.assertEqual(empty["status"], "no_setup")
        self.assertFalse(empty["orders_allowed"])

    def test_shorts_are_blocked(self):
        with self.assertRaises(ValueError):
            scan_intraday_mean_reversion(self.frame(), allow_shorts=True)


if __name__ == "__main__":
    unittest.main()
