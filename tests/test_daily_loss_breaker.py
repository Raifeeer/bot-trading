"""Breaker diario en dólares absolutos.

Los breakers porcentuales (`max_drawdown_daily_pct` 15%) se miden sobre la
cuenta completa: 15% de $99,689 son $14,953, así que a la escala del reto
$100->$200 no saltan nunca — harían falta ~19 pérdidas totales de $777 para
disparar uno. Con el tamaño de recuperación sin tope (decisión del dueño del
17 ago 2026) ese hueco es justo el que importa, y `max_daily_loss_usd` es el
único límite que de verdad corta una mala racha.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.manager import RiskManager  # noqa: E402


def _rm(**cfg):
    base = dict(mode="aggressive", max_drawdown_daily_pct=15.0,
                max_drawdown_total_pct=30.0, max_daily_loss_usd=400.0)
    base.update(cfg)
    rm = RiskManager(base)
    rm.capital = 99_689.15
    rm.reset_day(99_689.15)
    return rm


class TestAbsoluteDailyBreaker(unittest.TestCase):
    def test_fires_on_absolute_loss_the_percentage_would_miss(self):
        rm = _rm()
        # $500 de pérdida = 0.50% del equity: el breaker del 15% no la ve.
        rm.check_circuit_breakers(99_689.15 - 500.0)
        self.assertTrue(rm.is_halted(),
                        "el breaker absoluto debe cortar donde el % no llega")

    def test_does_not_fire_below_the_limit(self):
        rm = _rm()
        rm.check_circuit_breakers(99_689.15 - 399.0)
        self.assertFalse(rm.is_halted())

    def test_one_large_losing_entry_halts_the_day(self):
        """Una entrada de recuperación de ~$777 que pierde todo debe detener
        las entradas del resto del día en vez de encadenar otra igual."""
        rm = _rm()
        rm.check_circuit_breakers(99_689.15 - 777.0)
        self.assertTrue(rm.is_halted())

    def test_percentage_breaker_still_works(self):
        rm = _rm(max_daily_loss_usd=None)
        rm.check_circuit_breakers(99_689.15 * 0.84)  # -16%
        self.assertTrue(rm.is_halted())

    def test_absent_config_keeps_legacy_behaviour(self):
        """Sin la clave, nada cambia respecto al comportamiento histórico."""
        rm = _rm(max_daily_loss_usd=None)
        rm.check_circuit_breakers(99_689.15 - 5_000.0)  # -5%: bajo el 15%
        self.assertFalse(rm.is_halted())

    def test_profit_never_halts(self):
        rm = _rm()
        rm.check_circuit_breakers(99_689.15 + 1_000.0)
        self.assertFalse(rm.is_halted())

    def test_halt_blocks_new_positions(self):
        rm = _rm()
        rm.check_circuit_breakers(99_689.15 - 500.0)
        dec = rm.approve_position("TQQQ", object(), 10.0, 99_000.0, [])
        self.assertEqual(dec.decision, "REJECTED")
        self.assertIn("circuit breaker", dec.reason)


if __name__ == "__main__":
    unittest.main()
