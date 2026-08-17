"""Guarda-raíl matemático de la configuración de salida de prima.

Para un spread de débito, `options/strategy.py::evaluate_exit` cierra en:
    TP  -> prima == entry * tp_mult   => ganancia (tp_mult - 1) * entry
    SL  -> prima == entry * sl_mult   => pérdida  (1 - sl_mult) * entry

De ahí, el win rate mínimo para no perder dinero:
    p_be = (1 - sl_mult) / ((tp_mult - 1) + (1 - sl_mult))

Este test existe porque el 17 ago 2026 producción corría tp=1.4 / sl=0.25,
que exige un 65.2% de acierto, mientras que el corpus completo de 89
escenarios de backtest nunca superó el 64% (mediana 47%, p90 58%). Es decir:
una configuración matemáticamente perdedora para la precisión real del
motor, sin que ningún test lo impidiera.

El umbral de 55% no es arbitrario: es un acierto que varios escenarios del
corpus alcanzan de forma repetida, así que una config por debajo de esa
exigencia es al menos alcanzable. Si alguien vuelve a apretar el stop sin
subir el objetivo, este test falla y explica por qué.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Máximo win rate de equilibrio que consideramos alcanzable, según los win
# rates realmente observados en docs/backtests (mediana 47%, máx 64%).
MAX_BREAKEVEN_WR = 55.0


def breakeven_wr(tp_mult: float, sl_mult: float) -> float:
    gain = tp_mult - 1.0
    loss = 1.0 - sl_mult
    assert gain > 0, "tp_mult debe ser > 1 (objetivo por encima de la entrada)"
    assert loss > 0, "sl_mult debe ser < 1 (stop por debajo de la entrada)"
    return loss / (gain + loss) * 100.0


class TestBreakevenFormula(unittest.TestCase):
    def test_formula_known_values(self):
        # Simétrico: gana 50%, pierde 50% -> hace falta acertar la mitad.
        self.assertAlmostEqual(breakeven_wr(1.5, 0.5), 50.0, places=6)
        # La config que estaba en producción el 17 ago 2026.
        self.assertAlmostEqual(breakeven_wr(1.4, 0.25), 65.217391, places=4)
        # Dejar correr al ganador baja mucho la exigencia.
        self.assertAlmostEqual(breakeven_wr(2.0, 0.6), 28.571428, places=4)

    def test_monotonic_in_tp(self):
        """Subir el objetivo siempre reduce el acierto necesario."""
        prev = 100.0
        for tp in (1.2, 1.4, 1.6, 1.8, 2.0, 2.5):
            cur = breakeven_wr(tp, 0.5)
            self.assertLess(cur, prev)
            prev = cur


class TestProductionExitConfig(unittest.TestCase):
    """DEFECTO CONOCIDO — los dos tests de esta clase fallan a propósito.

    Documentan, en código ejecutable, que `config/config.yaml` corre hoy
    tp_premium_mult=1.4 / sl_premium_mult=0.25: un 65.2% de acierto exigido
    contra un 64% máximo histórico. Están marcados `expectedFailure` para
    que la suite siga en verde mientras se decide, con las rondas de
    backtesting out-of-sample, a qué valores mover la config (elegir el
    mejor in-sample es justo el error que advierte
    docs/skills/backtest_skill.md §8).

    Al corregir la config hay que RETIRAR los dos decoradores: entonces
    pasan y quedan como guarda-raíl permanente.
    """

    def _load_exit_cfg(self):
        from config import get_config
        import bot as B
        return B.premium_exit_cfg(get_config())

    @unittest.expectedFailure
    def test_production_breakeven_is_achievable(self):
        pec = self._load_exit_cfg()
        tp, sl = float(pec["tp_mult"]), float(pec["sl_mult"])
        be = breakeven_wr(tp, sl)
        self.assertLessEqual(
            be, MAX_BREAKEVEN_WR,
            msg=(f"\nLa config de salida exige un {be:.1f}% de acierto para "
                 f"empatar (tp_mult={tp}, sl_mult={sl}).\n"
                 f"El corpus de backtests nunca superó el 64% (mediana 47%), "
                 f"así que esta configuración pierde dinero por construcción.\n"
                 f"Sube tp_premium_mult y/o afloja sl_premium_mult en "
                 f"config/config.yaml hasta bajar de {MAX_BREAKEVEN_WR}%."))

    @unittest.expectedFailure
    def test_reward_risk_at_least_reasonable(self):
        """La relación ganancia/pérdida no debe ser peor que 0.8:1."""
        pec = self._load_exit_cfg()
        tp, sl = float(pec["tp_mult"]), float(pec["sl_mult"])
        rr = (tp - 1.0) / (1.0 - sl)
        self.assertGreaterEqual(
            rr, 0.8,
            msg=(f"Relación ganancia/pérdida {rr:.2f}:1 (tp={tp}, sl={sl}). "
                 f"Arriesgar mucho más de lo que se busca ganar exige un "
                 f"acierto que el motor no tiene."))


if __name__ == "__main__":
    unittest.main()
