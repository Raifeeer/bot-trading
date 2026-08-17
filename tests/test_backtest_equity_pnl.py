"""Las patas de acciones del backtest deben registrar P&L cuando el precio se mueve.

Cuarto bug del motor encontrado el 17 ago 2026, y el más silencioso: el bucle
diario refrescaba `pos["last_spot"]` con el cierre de cada día, y los cierres
valoraban la posición contra ese mismo campo:

    pos["last_spot"] = exit_spot          # bucle diario
    ...
    val = entry_net * cierre_hoy / pos["last_spot"]   # cierre  -> cociente 1

El cociente salía siempre 1, así que `pnl` era exactamente 0.0. Las patas de
acciones del motor `regime_aware` no podían registrar ganancia ni pérdida
jamás: 72 de 74 operaciones con pnl 0 y pnl MÁXIMO +0.0000. El motor parecía
no tener ninguna capacidad de ganar cuando en realidad el P&L se estaba
descartando.

El arreglo separa `entry_spot` (precio de entrada, inmutable, referencia de
valoración) de `last_spot` (último precio conocido, fallback si falta la barra
del día de salida).

Efecto medido en la ventana del drawdown -19% (feb-jun 2025):
    regime_aware      -> de 72/74 ceros y max +0.0000  a  0/74 ceros, +5.04%
    hold_weekly       -> de 6/55 ceros                 a  1/55 ceros, +16.61%
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from loop_backtests import _ref_spot, run_scenario  # noqa: E402


def _trending(n=320, pendiente=0.25, seed=1, start=50.0):
    """Serie con tendencia clara: si el motor valora bien, el P&L NO puede
    ser cero en todas las operaciones."""
    idx = pd.date_range("2025-01-02", periods=n, freq="B", tz="UTC")
    rng = np.random.default_rng(seed)
    close = start + np.arange(n) * pendiente + rng.standard_normal(n) * 0.3
    close = np.maximum(close, 1.0)
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": rng.integers(1_000_000, 5_000_000, n),
    }, index=idx)


class TestRefSpot(unittest.TestCase):
    def test_prefers_entry_spot_over_last_spot(self):
        pos = {"entry_spot": 100.0, "last_spot": 130.0}
        self.assertEqual(_ref_spot(pos), 100.0)

    def test_falls_back_to_last_spot_when_no_entry_spot(self):
        self.assertEqual(_ref_spot({"last_spot": 130.0}), 130.0)

    def test_falls_back_when_entry_spot_is_zero_or_none(self):
        self.assertEqual(_ref_spot({"entry_spot": 0.0, "last_spot": 42.0}), 42.0)
        self.assertEqual(_ref_spot({"entry_spot": None, "last_spot": 42.0}), 42.0)


class TestHoldLegsRegisterPnl(unittest.TestCase):
    def setUp(self):
        self.data = {s: _trending(seed=i, start=30.0 + 8 * i)
                     for i, s in enumerate(["AAA", "BBB", "CCC", "DDD"])}
        self.base = dict(
            tickers=list(self.data), risk_pct=0.15, max_pos=3, dte=21,
            delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.50, max_rv=None,
            anti_earnings=False, comision=0.0, window_days=None,
            window_dates=("2025-03-01", "2026-02-01"))

    def test_equity_legs_are_not_all_zero_pnl(self):
        """El corazón del bug: con precio en tendencia, es imposible que TODAS
        las operaciones de acciones cierren con pnl exactamente 0."""
        for motor in ("regime_aware", "regime_hold_cash", "hold_weekly", "hold"):
            with self.subTest(motor=motor):
                sc = dict(self.base, name=motor, motor=motor)
                _eq, tdf, _ec, _dd, _mx = run_scenario(motor, sc, self.data)
                if not len(tdf) or "pnl" not in tdf:
                    self.skipTest(f"{motor} no generó operaciones")
                ceros = int((tdf["pnl"] == 0).sum())
                self.assertLess(
                    ceros, len(tdf),
                    f"{motor}: las {len(tdf)} operaciones tienen pnl 0; el P&L "
                    f"se está descartando")

    def test_regime_aware_can_produce_a_winning_trade(self):
        """`regime_aware` llegó a tener pnl MÁXIMO +0.0000: no podía ganar."""
        sc = dict(self.base, name="ra", motor="regime_aware")
        _eq, tdf, _ec, _dd, _mx = run_scenario("ra", sc, self.data)
        if not len(tdf):
            self.skipTest("sin operaciones")
        self.assertGreater(
            float(tdf["pnl"].max()), 0.0,
            "ninguna operación gana: el P&L de las patas de acciones se pierde")


if __name__ == "__main__":
    unittest.main()
