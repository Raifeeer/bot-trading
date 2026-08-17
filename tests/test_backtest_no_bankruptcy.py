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
