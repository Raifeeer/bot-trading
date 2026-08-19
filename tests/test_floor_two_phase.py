"""Piso de equity: recuperación bajo $100,000 y reto sobre el objetivo.

Mientras equity < $100,000 rige recovery_floor=$99,000 para evitar el bloqueo
circular observado con la cuenta de producción. Al tocar $100,000 se activa el
piso de reto=$99,900. El latch se conserva para trazabilidad, pero debajo del
objetivo la fase efectiva vuelve a recuperación segura.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.floor import DEFAULT_FLOOR_CFG, active_floor, check_floor

CFG = dict(DEFAULT_FLOOR_CFG)


class TestRecoveryPhase(unittest.TestCase):
    def test_below_target_uses_recovery_floor_and_can_trade(self):
        """El caso real del 17 ago 2026: $99,689 debe poder operar."""
        state = {}
        r = check_floor(99_689.15, state, CFG)
        self.assertEqual(r["phase"], "recuperacion")
        self.assertEqual(r["floor"], 99_000.0)
        self.assertFalse(r["below_floor"], "debe poder abrir posiciones")
        self.assertFalse(r["challenge_armed"])

    def test_current_production_equity_can_trade(self):
        r = check_floor(99_288.65, {}, CFG)
        self.assertEqual(r["phase"], "recuperacion")
        self.assertFalse(r["below_floor"])

    def test_recovery_floor_still_protects(self):
        """La recuperación no es 'sin control de riesgo': su piso frena."""
        state = {}
        r = check_floor(98_950.0, state, CFG)
        self.assertEqual(r["phase"], "recuperacion")
        self.assertTrue(r["below_floor"])
        self.assertIn("PISO ROTADO", r["reason"])


class TestChallengeArming(unittest.TestCase):
    def test_reaching_target_arms_challenge_once(self):
        state = {}
        check_floor(99_689.15, state, CFG)          # recuperación
        r = check_floor(100_000.0, state, CFG)      # toca el objetivo
        self.assertTrue(r["challenge_armed"])
        self.assertEqual(r["phase"], "reto")
        self.assertEqual(r["floor"], 99_900.0)
        self.assertTrue(r["crossed"])
        self.assertIn("OBJETIVO ALCANZADO", r["reason"])
        self.assertTrue(state["_challenge_armed"])

        # No debe volver a anunciarlo en cada tick.
        r2 = check_floor(100_050.0, state, CFG)
        self.assertFalse(r2["crossed"])

    def test_latch_allows_recovery_below_target(self):
        """El latch histórico no debe crear un bloqueo circular bajo $100k."""
        state = {}
        check_floor(100_000.0, state, CFG)   # arma
        r = check_floor(99_950.0, state, CFG)
        self.assertEqual(r["phase"], "recuperacion")
        self.assertEqual(r["floor"], 99_000.0)
        self.assertFalse(r["below_floor"])
        self.assertFalse(r["challenge_armed"])
        self.assertTrue(state["_challenge_armed"], "latch de trazabilidad")

        # El piso de recuperación sigue bloqueando por debajo de $99,000.
        r2 = check_floor(98_950.0, state, CFG)
        self.assertEqual(r2["phase"], "recuperacion")
        self.assertEqual(r2["floor"], 99_000.0)
        self.assertTrue(r2["below_floor"])

        # Al recuperar el objetivo vuelve a regir el piso del reto.
        r3 = check_floor(100_000.0, state, CFG)
        self.assertEqual(r3["phase"], "reto")
        self.assertEqual(r3["floor"], 99_900.0)
        self.assertFalse(r3["below_floor"])
        self.assertTrue(r3["challenge_armed"])

    def test_equity_above_target_arms_even_without_prior_state(self):
        """Arranque en frío con equity ya sobre el objetivo: fase reto."""
        floor, phase, armed = active_floor(100_500.0, {}, CFG)
        self.assertEqual((floor, phase, armed), (99_900.0, "reto", True))

    def test_active_floor_does_not_mutate_state(self):
        state = {}
        active_floor(100_500.0, state, CFG)
        self.assertEqual(state, {}, "active_floor no debe escribir en el estado")


class TestEntryGateIntegration(unittest.TestCase):
    def test_gate_open_in_recovery_and_closed_below_recovery_floor(self):
        """Reproduce la condición de bot.py: bull + not below_floor."""
        for equity, esperado in ((99_689.15, True), (99_288.65, True),
                                 (98_950.0, False)):
            state = {}
            fr = check_floor(equity, state, CFG)
            regime = {"regime": "bull", "floor": fr}
            gate = (regime["regime"] == "bull"
                    and not regime["floor"]["below_floor"])
            self.assertEqual(gate, esperado, f"equity {equity}")


if __name__ == "__main__":
    unittest.main()
