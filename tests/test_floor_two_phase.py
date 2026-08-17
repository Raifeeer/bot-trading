"""Piso de equity en dos fases: recuperación -> reto, con latch permanente.

Decisión del dueño (17 ago 2026): con la cuenta en $99,689 y el piso del reto
en $99,900 el bot quedaba bloqueado en círculo (necesitaba ganar para operar y
operar para ganar). Se introduce una fase de RECUPERACIÓN con un piso más bajo
y objetivo $100,000; al tocarlo, el reto $100->$200 queda ARMADO de forma
permanente y rige el piso de $99,900.

Lo que estos tests protegen sobre todo es el latch: sin él, romper el piso del
reto devolvería al bot a modo recuperación —que tiene un piso más bajo— y el
piso de $99,900 no protegería nada. El recovery_floor actual es $99,000 para
permitir recuperar desde el equity de producción observado ($99,288.65).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.floor import check_floor, active_floor, DEFAULT_FLOOR_CFG  # noqa: E402

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

    def test_latch_survives_drop_below_target(self):
        """CLAVE: tras armar el reto, caer bajo $100k NO devuelve a
        recuperación — si lo hiciera, el piso de $99,900 sería inútil."""
        state = {}
        check_floor(100_000.0, state, CFG)   # arma
        r = check_floor(99_950.0, state, CFG)
        self.assertEqual(r["phase"], "reto")
        self.assertEqual(r["floor"], 99_900.0)
        self.assertFalse(r["below_floor"])

        # Y romper el piso del reto bloquea, sin relajarse al piso bajo.
        r2 = check_floor(99_850.0, state, CFG)
        self.assertEqual(r2["phase"], "reto")
        self.assertEqual(r2["floor"], 99_900.0)
        self.assertTrue(r2["below_floor"])
        self.assertNotEqual(r2["floor"], 99_000.0,
                            "no debe relajarse al piso de recuperación")

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
