"""Pruebas deterministas del motor bearish breakdown/retest."""
from __future__ import annotations

import unittest

import pandas as pd

from strategies.bearish_breakdown_retest import evaluate_breakdown_retest


def _frame(rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2026-08-19 14:30", periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


class TestBearishBreakdownRetest(unittest.TestCase):
    def test_confirms_breakdown_retest_with_volume(self):
        rows = [(100.2, 100.6, 99.9, 100.2, 100.0)] * 45
        rows.extend([
            (99.0, 99.2, 97.8, 98.2, 160.0),
            (99.4, 100.2, 98.4, 98.8, 100.0),
        ])
        result = evaluate_breakdown_retest(
            _frame(rows), lookback=20, volume_min=1.1, retest_max_bars=2
        )
        self.assertEqual(result["signal"], "bearish_breakdown_retest")
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["direction"], "bear")
        self.assertFalse(result["orders_allowed"])
        self.assertLess(result["target_price"], result["stop_price"])
        self.assertLess(result["break_timestamp"], result["confirmation_timestamp"])

    def test_recovered_support_invalidates_retest(self):
        rows = [(100.2, 100.6, 99.9, 100.2, 100.0)] * 45
        rows.extend([
            (99.0, 99.2, 97.8, 98.2, 160.0),
            (99.8, 100.8, 99.5, 100.4, 100.0),
        ])
        result = evaluate_breakdown_retest(
            _frame(rows), lookback=20, volume_min=1.1, retest_max_bars=2
        )
        self.assertNotEqual(result["status"], "confirmed")
        self.assertFalse(result["orders_allowed"])

    def test_insufficient_data_is_neutral(self):
        rows = [(100.2, 100.6, 99.9, 100.2, 100.0)] * 20
        result = evaluate_breakdown_retest(_frame(rows))
        self.assertEqual(result["signal"], "none")
        self.assertEqual(result["status"], "insufficient_data")


if __name__ == "__main__":
    unittest.main()
