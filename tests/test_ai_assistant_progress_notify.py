"""answer() debe propagar `notify` hasta cada etapa lenta (búsqueda de
ticker, indicadores técnicos, llamada al LLM), no solo el aviso genérico
inicial de telegram_bot. Sin red real: se fuerza ENABLED y se mockean
yfinance/data.earnings/_call_llm."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from state import ai_assistant  # noqa: E402


def _synthetic_hist(n=260):
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
    return pd.DataFrame({
        "Open": close - 0.3, "High": close + 0.6, "Low": close - 0.6,
        "Close": close, "Volume": rng.integers(1_000_000, 5_000_000, n),
    }, index=idx)


class TestProgressNotify(unittest.TestCase):
    def test_answer_notifies_each_slow_stage(self):
        msgs = []

        def _ticker_factory(sym):
            t = MagicMock()
            if sym.upper() == "AAPL":
                t.fast_info.last_price = 150.0
                t.fast_info.trailing_pe = 20.0
                t.history.return_value = _synthetic_hist()
            else:
                t.fast_info.last_price = None  # candidato falso (ej. "de")
            return t

        with patch.object(ai_assistant, "ENABLED", True), \
             patch.object(ai_assistant, "_build_context", return_value="sin posiciones"), \
             patch.object(ai_assistant, "_call_llm", return_value="respuesta IA"), \
             patch("yfinance.Ticker", side_effect=_ticker_factory), \
             patch("data.earnings.get_earnings", return_value={}):
            resp = ai_assistant.answer("qué opinas de AAPL", notify=msgs.append)

        self.assertEqual(resp, "respuesta IA")
        joined = " | ".join(msgs).lower()
        self.assertIn("aapl", joined)
        self.assertIn("señal técnica".lower(), joined.replace("é", "é"))
        self.assertTrue(any("generando" in m.lower() for m in msgs))

    def test_answer_without_notify_still_works(self):
        with patch.object(ai_assistant, "ENABLED", True), \
             patch.object(ai_assistant, "_build_context", return_value="sin posiciones"), \
             patch.object(ai_assistant, "_has_ticker_hint", return_value=False), \
             patch.object(ai_assistant, "_call_llm", return_value="respuesta IA"):
            resp = ai_assistant.answer("hola, cómo estás")
        self.assertEqual(resp, "respuesta IA")


if __name__ == "__main__":
    unittest.main()
