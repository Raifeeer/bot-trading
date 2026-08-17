"""El universo declarado por el escenario debe respetarse de verdad.

Bug encontrado el 17 ago 2026: los bucles de entrada de las rutas no-regime
de `run_scenario` iteran `sorted(data.items())`, es decir TODOS los tickers
que el llamador descargó, ignorando `sc["tickers"]`. Consecuencia: dos
escenarios con universos distintos devolvían resultados idénticos byte a
byte, y todas las conclusiones "por universo" del corpus S1-S89 (tickers
baratos vs ETFs vs tech) estaban midiendo lo mismo.

El arreglo filtra `data` al universo al entrar en `run_scenario`, con lo que
cubre a la vez las rutas regime, hold y opciones.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def _synthetic(n=320, seed=0, start=90.0):
    idx = pd.date_range("2025-06-02", periods=n, freq="B", tz="UTC")
    rng = np.random.default_rng(seed)
    close = start + np.cumsum(rng.standard_normal(n) * 0.4)
    close = np.maximum(close, 1.0)
    return pd.DataFrame({
        "open": close - 0.2, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": rng.integers(2_000_000, 6_000_000, n),
    }, index=idx)


class TestUniverseIsRespected(unittest.TestCase):
    def setUp(self):
        self.data = {s: _synthetic(seed=i, start=20.0 + 10 * i)
                     for i, s in enumerate(["AAA", "BBB", "CCC", "DDD"])}
        self.base = dict(
            motor="smc_daily", risk_pct=0.15, max_pos=3, dte=30,
            delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.50, max_rv=None,
            anti_earnings=False, comision=0.65,
            window_dates=("2025-08-01", "2026-07-01"), window_days=None)

    def test_never_trades_outside_declared_universe(self):
        from loop_backtests import run_scenario
        sc = dict(self.base, name="u", tickers=["AAA", "BBB"])
        _eq, tdf, _ec, _dd, _mx = run_scenario("u", sc, self.data)
        if len(tdf):
            fuera = sorted(set(tdf["symbol"]) - {"AAA", "BBB"})
            self.assertEqual(fuera, [], f"operó fuera del universo: {fuera}")

    def test_unknown_universe_raises_instead_of_silently_using_all(self):
        """Un universo que no intersecta los datos debe fallar ruidosamente,
        no caer de vuelta a 'todos los tickers'."""
        from loop_backtests import run_scenario
        sc = dict(self.base, name="x", tickers=["NOEXISTE1", "NOEXISTE2"])
        with self.assertRaises(ValueError):
            run_scenario("x", sc, self.data)

    def test_data_dict_of_caller_is_not_mutated(self):
        """El filtrado no debe vaciar el dict compartido entre escenarios
        (los workers reutilizan el mismo dataset)."""
        from loop_backtests import run_scenario
        antes = set(self.data)
        sc = dict(self.base, name="u2", tickers=["AAA"])
        try:
            run_scenario("u2", sc, self.data)
        except Exception:  # noqa: BLE001
            pass
        self.assertEqual(set(self.data), antes)


if __name__ == "__main__":
    unittest.main()
