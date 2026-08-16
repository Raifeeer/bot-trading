"""spot_iv_from_feed no debe colgar el tick si feed.history() nunca retorna
(yfinance puede colgarse sin lanzar excepción). Se simula un feed cuyo
history() bloquea indefinidamente y se verifica que la función retorna
(None, None) dentro de un tiempo acotado en vez de esperar para siempre."""
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from options import option_details  # noqa: E402


class _HangingFeed:
    def history(self, symbols, interval, days):
        time.sleep(3600)  # nunca debería completarse dentro del test
        return {}


class _FastFeed:
    def history(self, symbols, interval, days):
        import pandas as pd
        idx = pd.date_range("2025-01-01", periods=20, freq="B")
        return {symbols[0]: pd.DataFrame({"close": [100.0 + i for i in range(20)]}, index=idx)}


class TestSpotIvTimeout(unittest.TestCase):
    def test_hanging_feed_returns_none_within_timeout(self):
        with patch.object(option_details, "_SPOT_IV_TIMEOUT_S", 0.2):
            start = time.monotonic()
            spot, iv = option_details.spot_iv_from_feed(_HangingFeed(), "TQQQ")
            elapsed = time.monotonic() - start
        self.assertIsNone(spot)
        self.assertIsNone(iv)
        self.assertLess(elapsed, 2.0)

    def test_fast_feed_returns_values(self):
        with patch.object(option_details, "_SPOT_IV_TIMEOUT_S", 5.0):
            spot, iv = option_details.spot_iv_from_feed(_FastFeed(), "TQQQ")
        self.assertIsNotNone(spot)


if __name__ == "__main__":
    unittest.main()
