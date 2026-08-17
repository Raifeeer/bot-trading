"""Dimensionamiento por fase del piso (decisión del dueño, 17 ago 2026).

En fase `recuperacion` el bot opera SIN el tope de prima de $12, escalando
contratos para cerrar la brecha hasta $100,000 en un acierto. Al armarse el
reto vuelve al comportamiento regular (tope de config, 1 contrato), sin fecha
que recordar: lo gobierna el latch de risk/floor.py.

AVISO que estos tests dejan por escrito: la prima necesaria para cerrar la
brecha ($777 para $311 con TP +40%) SUPERA el margen hasta el piso de
recuperación ($289), asi que una sola entrada perdedora puede dejar el equity
bajo el piso. El piso solo bloquea entradas nuevas; no limita la pérdida de
una posición ya abierta. Es el coste aceptado de la decisión.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot as B  # noqa: E402


class _Leg:
    def __init__(self, qty, symbol="TQQQ260918C00085000", mid=2.0):
        self.quantity = qty
        self.contract = type("C", (), {
            "symbol": symbol, "ask": mid + 0.05, "bid": mid - 0.05,
            "mid": mid, "last": mid, "multiplier": 100})()


class _Structure:
    def __init__(self, premium, name="call_spread_X_1_2"):
        self.name = name
        self._premium = premium
        self.legs = [_Leg(+1), _Leg(-1, "TQQQ260918C00100000", 0.5)]

    @property
    def net_premium(self):
        return self._premium


CFG = {
    "universo": {"options_reto": {"max_premium_net": 12.0,
                                  "tp_premium_mult": 1.4,
                                  "sl_premium_mult": 0.25,
                                  "close_dte": 7}},
    "risk": {},
    "execution": {"order_type": "limit", "limit_offset_pct": 0.1},
}


class TestRecoverySizing(unittest.TestCase):
    def test_recovery_phase_lifts_cap_and_targets_the_gap(self):
        floor_res = dict(phase="recuperacion", target=100_000.0, floor=99_400.0)
        s = B.recovery_sizing(99_689.15, floor_res, CFG)
        self.assertTrue(s["unlimited"])
        self.assertIsNone(s["max_premium_net"], "sin tope en recuperación")
        # brecha 310.85 / (1.4-1) = 777.1
        self.assertAlmostEqual(s["target_premium"], 777.125, places=2)

    def test_challenge_phase_restores_regular_cap(self):
        floor_res = dict(phase="reto", target=100_000.0, floor=99_900.0)
        s = B.recovery_sizing(100_050.0, floor_res, CFG)
        self.assertFalse(s["unlimited"])
        self.assertEqual(s["max_premium_net"], 12.0)
        self.assertIsNone(s["target_premium"])

    def test_no_gap_means_no_target(self):
        floor_res = dict(phase="recuperacion", target=100_000.0, floor=99_400.0)
        s = B.recovery_sizing(100_000.0, floor_res, CFG)
        self.assertEqual(s["target_premium"], 0.0)


class TestContractsForTarget(unittest.TestCase):
    def test_scales_to_reach_target(self):
        st = _Structure(150.0)          # $150 por contrato
        n = B.contracts_for_target(st, 777.0, cash_disponible=98_000.0)
        self.assertEqual(n, 5)          # 5 x 150 = 750 <= 777

    def test_never_below_one(self):
        st = _Structure(900.0)          # más caro que el objetivo
        self.assertEqual(B.contracts_for_target(st, 777.0, 98_000.0), 1)

    def test_capped_by_available_cash(self):
        st = _Structure(150.0)
        n = B.contracts_for_target(st, 777.0, cash_disponible=400.0)
        self.assertEqual(n, 2)          # solo caben 2 x 150 = 300

    def test_zero_premium_is_safe(self):
        st = _Structure(0.0)
        self.assertEqual(B.contracts_for_target(st, 777.0, 98_000.0), 1)


class TestOrderSpecsScaling(unittest.TestCase):
    def test_both_legs_scale_equally_keeping_defined_risk(self):
        st = _Structure(150.0)
        specs = B._option_order_specs(st, CFG, contracts=5)
        self.assertEqual([s["qty"] for s in specs], [5, 5],
                         "las dos patas deben escalar igual (riesgo definido)")

    def test_default_is_one_contract(self):
        st = _Structure(150.0)
        specs = B._option_order_specs(st, CFG)
        self.assertEqual([s["qty"] for s in specs], [1, 1])

    def test_sides_are_preserved_when_scaling(self):
        st = _Structure(150.0)
        specs = B._option_order_specs(st, CFG, contracts=3)
        self.assertEqual([s["side"] for s in specs], ["buy", "sell"])


class TestDocumentedRiskOfTheDecision(unittest.TestCase):
    def test_target_premium_exceeds_margin_to_floor(self):
        """Deja constancia numérica: el tamaño objetivo puede romper el piso."""
        equity, floor = 99_689.15, 99_400.0
        floor_res = dict(phase="recuperacion", target=100_000.0, floor=floor)
        s = B.recovery_sizing(equity, floor_res, CFG)
        margen = equity - floor
        self.assertGreater(
            s["target_premium"], margen,
            "si esto deja de cumplirse, revisar el aviso de riesgo asociado")
        self.assertLess(equity - s["target_premium"], floor)


if __name__ == "__main__":
    unittest.main()
