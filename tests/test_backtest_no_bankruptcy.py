"""El motor de backtest no puede terminar con equity negativo.

El 17 ago 2026, la ronda 1 de walk-forward devolvió -102.0% en 38 corridas:
imposible, porque un spread de débito no puede perder más que la prima
pagada. Causa: `equity` solo se actualizaba al CERRAR (`equity += pnl`), así
que el capital comprometido en posiciones abiertas no se descontaba, y con
`max_pos` posiciones simultáneas el motor gastaba más de lo que tenía. Las
comisiones sobre una cuenta ya casi vacía terminaban de empujarla a negativo.

Este test recorre los CSV de equity de cualquier corrida presente y exige la
invariante. Si no hay corridas en disco, valida la invariante directamente
sobre un escenario sintético corto.
"""
import glob
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNoNegativeEquity(unittest.TestCase):
    def test_equity_curves_on_disk_never_go_negative(self):
        out_dir = os.environ.get("BT_OUT", "")
        paths = glob.glob(os.path.join(out_dir, "bt_*_equity.csv")) if out_dir else []
        if not paths:
            self.skipTest("sin curvas de equity en disco (define BT_OUT)")
        malos = []
        for p in paths:
            try:
                df = pd.read_csv(p)
            except Exception:  # noqa: BLE001
                continue
            if "equity" in df.columns and len(df) and df["equity"].min() < 0:
                malos.append((os.path.basename(p), float(df["equity"].min())))
        self.assertEqual(malos, [], f"curvas con equity negativo: {malos}")

    def test_entry_gate_respects_committed_capital(self):
        """La condición de entrada debe mirar el capital DISPONIBLE
        (equity menos lo comprometido), no el equity total."""
        import inspect
        import loop_backtests as L
        src = inspect.getsource(L.run_scenario)
        self.assertIn("committed", src,
                      "run_scenario debe descontar el capital comprometido")
        self.assertIn("available", src,
                      "run_scenario debe gatear las entradas por disponible")
        # El gate antiguo comparaba contra equity*0.5 sin descontar nada.
        self.assertNotIn("min(risk_budget, equity * 0.5)", src,
                         "queda el gate antiguo que ignora lo comprometido")

    def test_all_equity_paths_stay_non_negative(self):
        """Prueba de comportamiento sobre las CUATRO contabilidades de equity
        del motor (`equity`, `equity2`, `equity3`, `equity3b`).

        El bug original solo se veía en las rutas de 'hold': parchear una
        dejaba las otras rotas (whack-a-mole entre código duplicado). Este
        test ejerce un motor de cada familia con una cuenta que se agota, y
        exige que ninguna curva baje de cero.
        """
        import numpy as np
        import pandas as pd
        from loop_backtests import run_scenario

        # Serie bajista fuerte: agota la cuenta y fuerza el caso límite.
        idx = pd.date_range("2025-01-02", periods=300, freq="B", tz="UTC")
        rng = np.random.default_rng(7)
        data = {}
        for i, s in enumerate(["AAA", "BBB", "CCC", "DDD"]):
            close = np.maximum(
                60.0 - np.linspace(0, 45, 300) + rng.standard_normal(300) * 0.6,
                1.0)
            data[s] = pd.DataFrame({
                "open": close, "high": close * 1.01, "low": close * 0.99,
                "close": close,
                "volume": rng.integers(1_000_000, 4_000_000, 300)}, index=idx)

        base = dict(risk_pct=0.15, max_pos=3, dte=21, delta_l=0.30,
                    delta_s=0.10, tp=1.5, sl=0.50, max_rv=None,
                    anti_earnings=False, comision=0.65,
                    tickers=list(data), window_days=None,
                    window_dates=("2025-02-01", "2026-02-01"))
        for motor in ("smc_daily", "hold_weekly", "regime_hold_cash",
                      "regime_aware"):
            with self.subTest(motor=motor):
                sc = dict(base, name=motor, motor=motor)
                _eq, _t, ecdf, _dd, _mx = run_scenario(motor, sc, data)
                if len(ecdf):
                    self.assertGreaterEqual(
                        float(ecdf["equity"].min()), 0.0,
                        f"{motor}: la curva de equity baja de cero")

    def test_committed_capital_math(self):
        """Con 3 posiciones abiertas de $15 sobre $100, quedan $55 y una
        cuarta de $60 no debe caber."""
        equity = 100.0
        open_pos = [{"entry_net": 15.0} for _ in range(3)]
        committed = sum(p["entry_net"] for p in open_pos)
        available = equity - committed
        self.assertEqual(committed, 45.0)
        self.assertEqual(available, 55.0)
        self.assertGreater(60.0, available)   # no cabe
        self.assertLessEqual(50.0, available)  # sí cabe


if __name__ == "__main__":
    unittest.main()
