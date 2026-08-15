"""_technical_snapshot() del asistente de Telegram debe reutilizar el mismo
código que decide operaciones reales (SwingTrend, detect_choch), no un
análisis inventado aparte para el chat. Datos sintéticos: yfinance no
funciona en este sandbox (curl_cffi choca con el proxy)."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from state.ai_assistant import _technical_snapshot  # noqa: E402


def _synthetic_ohlcv(n=260, seed=1, trend=20.0):
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.5) + np.linspace(0, trend, n)
    return pd.DataFrame({
        "Open": close - 0.3, "High": close + 0.6, "Low": close - 0.6,
        "Close": close, "Volume": rng.integers(1_000_000, 5_000_000, n),
    }, index=idx)


class TestTechnicalSnapshot(unittest.TestCase):
    def test_returns_real_signal_and_indicators(self):
        df = _synthetic_ohlcv()
        out = _technical_snapshot("TEST", df)
        self.assertIn("señal swing_trend actual", out)
        self.assertIn("CHoCH", out)
        self.assertIn("RSI14", out)
        # Nunca debe fabricar una recomendación fuera de lo que scan() devuelve
        self.assertTrue("NONE" in out or "long" in out.lower() or "exit" in out.lower())

    def test_empty_on_insufficient_history(self):
        df = _synthetic_ohlcv(n=30)
        out = _technical_snapshot("TEST", df)
        self.assertEqual(out, "")

    def test_never_raises_on_malformed_frame(self):
        df = pd.DataFrame({"close": [1, 2, 3]})  # sin columnas OHLCV completas
        out = _technical_snapshot("TEST", df)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
